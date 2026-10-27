import re
import chromadb
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer

_client = chromadb.PersistentClient(path="chroma_db")
_col = _client.get_or_create_collection("notes")
_model = SentenceTransformer("all-MiniLM-L6-v2")

CHUNK_SIZE = 800
OVERLAP = 100

_JUNK = ("mrcet", "year/", "lecture notes", "python programming", "page ")
_BAD_START = {
    "output", "example", "examples", "method", "methods", "description", "syntax",
    "program", "result", "results", "note", "table", "figure", "fig", "step",
    "operator", "function", "returns", "parameters", "parameter",
}
_BAD_ANY = {"description"}
_BAD_EXACT = {
    "true", "false", "none", "general", "index", "syllabus", "objectives",
    "outcomes", "text books", "reference books", "unit", "contents",
}
_SMALL = {"and", "or", "of", "in", "the", "to", "a", "an", "vs", "for", "with", "on", "as"}


def extract_pages(path, filename):
    """Returns list of (page_number, text)."""
    if filename.lower().endswith(".pdf"):
        reader = PdfReader(path)
        return [(i + 1, p.extract_text() or "") for i, p in enumerate(reader.pages)]
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    # treat every ~3000 chars of a txt file as a "page"
    return [(i // 3000 + 1, text[i:i + 3000]) for i in range(0, len(text), 3000)]


def _titleish(words):
    caps = [w for w in words if w.lower() not in _SMALL]
    return bool(caps) and all(w[0].isupper() for w in caps if w[0].isalpha())


def _is_heading(line):
    s = line.strip()
    if not (4 <= len(s) <= 60):
        return False
    if s.endswith((".", ",", ";", ":")):
        return False
    low = s.lower()
    if any(j in low for j in _JUNK):
        return False
    if re.search(r"[=()\[\]{}\"'<>#@$%^*+/\\|]", s):   # code lines
        return False
    if not re.match(r"^[A-Za-z0-9]", s):
        return False
    words = s.split()
    if len(words) > 8:
        return False
    lw = low.split()
    if lw[0] in _BAD_START or any(w in _BAD_ANY for w in lw) or low in _BAD_EXACT:
        return False
    rest = re.sub(r"^\d+(\.\d+)*[\s.)]+", "", s)
    if rest != s:                                        # numbered heading like "4.2 Lists"
        rw = rest.split()
        return bool(rw) and _titleish(rw) and rest.lower() not in _BAD_EXACT
    if s.isupper() and len(s) >= 5 and not s.replace(" ", "").isdigit():
        return True
    return _titleish(words)


def _clean_heading(s):
    return re.sub(r"^\d+(\.\d+)*[\s.)]+", "", s.strip())


def chunk_pages(pages):
    """Returns list of dicts: text, page, heading. Headings found WITHOUT an LLM.
    Each chunk gets the heading in effect where the chunk starts."""
    chunks = []
    heading = "General"
    for page_no, text in pages:
        full, marks = "", []
        for line in text.split("\n"):
            s = line.strip()
            if not s:
                continue
            if _is_heading(s):
                heading = _clean_heading(s)
            if not marks or marks[-1][1] != heading:
                marks.append((len(full), heading))
            full += s + " "
        start = 0
        while start < len(full):
            piece = full[start:start + CHUNK_SIZE]
            if len(piece.strip()) > 50:
                h = [m[1] for m in marks if m[0] <= start][-1]
                chunks.append({"text": piece.strip(), "page": page_no, "heading": h})
            start += CHUNK_SIZE - OVERLAP
    return chunks


def index_document(doc):
    pages = extract_pages(doc.file.path, doc.name)
    chunks = chunk_pages(pages)
    if not chunks:
        return 0
    texts = [c["text"] for c in chunks]
    embeddings = _model.encode(texts).tolist()
    _col.add(
        ids=[f"{doc.id}_{i}" for i in range(len(chunks))],
        documents=texts,
        embeddings=embeddings,
        metadatas=[
            {
                "user_id": doc.user_id,
                "doc_id": doc.id,
                "doc_name": doc.name,
                "page": c["page"],
                "heading": c["heading"],
            }
            for c in chunks
        ],
    )
    return len(chunks)


def _where(user_id, doc_id=None):
    if doc_id:
        return {"$and": [{"user_id": user_id}, {"doc_id": int(doc_id)}]}
    return {"user_id": user_id}


def search(user_id, query, doc_id=None, k=5):
    """Only the top-k relevant chunks are ever returned."""
    emb = _model.encode([query]).tolist()
    res = _col.query(query_embeddings=emb, n_results=k, where=_where(user_id, doc_id))
    out = []
    for text, meta in zip(res["documents"][0], res["metadatas"][0]):
        out.append({"text": text, **meta})
    return out


def get_headings(user_id, doc_id):
    """Unique headings in order. Used for summarization (no full text sent)."""
    res = _col.get(where=_where(user_id, doc_id), include=["metadatas"])
    seen, headings = set(), []
    items = sorted(res["metadatas"], key=lambda m: m["page"])
    for m in items:
        if m["heading"] not in seen:
            seen.add(m["heading"])
            headings.append(m["heading"])
    return headings


def delete_document(doc_id):
    _col.delete(where={"doc_id": int(doc_id)})