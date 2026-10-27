import json
import random
import re

from django.contrib.auth.models import User
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.authtoken.models import Token

from .models import Document, Conversation, Message
from . import rag, llm

MAX_CHUNKS = 4          # chunks sent per chat question
MAX_HEADINGS = 40       # headings sent for a summary
MAX_MCQ = 10


# ---------- AUTH ----------
@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    u, p = request.data.get("username"), request.data.get("password")
    if not u or not p:
        return Response({"error": "username and password required"}, status=400)
    if User.objects.filter(username=u).exists():
        return Response({"error": "username taken"}, status=400)
    user = User.objects.create_user(username=u, password=p)
    token, _ = Token.objects.get_or_create(user=user)
    return Response({"token": token.key, "username": u})


# ---------- DOCUMENTS ----------
@api_view(["GET", "POST"])
def documents(request):
    if request.method == "POST":
        f = request.FILES.get("file")
        if not f or not f.name.lower().endswith((".pdf", ".txt")):
            return Response({"error": "Upload a PDF or TXT file"}, status=400)
        doc = Document.objects.create(
            user=request.user, name=f.name, file=f, size=f.size
        )
        try:
            n = rag.index_document(doc)
            doc.status = "indexed" if n else "empty"
        except Exception as e:
            doc.status = "failed"
            print("Index error:", e)
        doc.save()
    docs = Document.objects.filter(user=request.user).order_by("-uploaded_at")
    return Response([
        {
            "id": d.id, "name": d.name, "size": d.size,
            "status": d.status, "uploaded_at": d.uploaded_at,
        }
        for d in docs
    ])


@api_view(["DELETE"])
def delete_doc(request, doc_id):
    try:
        d = Document.objects.get(id=doc_id, user=request.user)
    except Document.DoesNotExist:
        return Response(status=404)
    rag.delete_document(d.id)
    d.file.delete()
    d.delete()
    return Response(status=204)


# ---------- CHAT (RAG) ----------
CHAT_SYSTEM = (
    "You are a study assistant. Answer ONLY using the provided notes excerpts. "
    "If the answer is not in the excerpts, say you could not find it in the "
    "student's notes. Be clear and concise. Use a markdown table when comparing things."
)


@api_view(["POST"])
def chat(request):
    question = (request.data.get("message") or "").strip()
    if not question:
        return Response({"error": "message required"}, status=400)
    doc_id = request.data.get("doc_id") or None
    conv_id = request.data.get("conversation_id")

    if conv_id:
        try:
            conv = Conversation.objects.get(id=conv_id, user=request.user)
        except Conversation.DoesNotExist:
            return Response({"error": "conversation not found"}, status=404)
    else:
        conv = Conversation.objects.create(user=request.user, title=question[:50])

    # ONLY the top chunks are sent to the LLM, never the whole document
    chunks = rag.search(request.user.id, question, doc_id=doc_id, k=MAX_CHUNKS)
    if not chunks:
        answer = "I couldn't find anything in your notes. Please upload a document first."
        sources = []
    else:
        context = "\n\n".join(
            f"[{c['doc_name']}, page {c['page']}]\n{c['text']}" for c in chunks
        )
        history = list(conv.messages.order_by("-id")[:4])[::-1]
        msgs = [{"role": m.role, "content": m.content} for m in history]
        msgs.append({
            "role": "user",
            "content": f"Notes excerpts:\n{context}\n\nQuestion: {question}",
        })
        try:
            answer = llm.chat(CHAT_SYSTEM, msgs, max_tokens=600)
        except Exception as e:
            return Response({"error": f"LLM error: {e}"}, status=500)
        seen, sources = set(), []
        for c in chunks:
            key = (c["doc_name"], c["page"])
            if key not in seen:
                seen.add(key)
                sources.append({"doc": c["doc_name"], "page": c["page"]})

    Message.objects.create(conversation=conv, role="user", content=question)
    Message.objects.create(
        conversation=conv, role="assistant", content=answer, sources=sources
    )
    return Response({"conversation_id": conv.id, "answer": answer, "sources": sources})


# ---------- CHAT HISTORY ----------
@api_view(["GET"])
def conversations(request):
    convs = Conversation.objects.filter(user=request.user).order_by("-created_at")
    out = []
    for c in convs:
        first = c.messages.filter(role="user").first()
        out.append({
            "id": c.id,
            "title": c.title,
            "preview": first.content if first else "",
            "created_at": c.created_at,
        })
    return Response(out)


@api_view(["GET", "DELETE"])
def conversation_detail(request, conv_id):
    try:
        c = Conversation.objects.get(id=conv_id, user=request.user)
    except Conversation.DoesNotExist:
        return Response(status=404)
    if request.method == "DELETE":
        c.delete()
        return Response(status=204)
    return Response({
        "id": c.id,
        "title": c.title,
        "messages": [
            {"role": m.role, "content": m.content, "sources": m.sources,
             "created_at": m.created_at}
            for m in c.messages.order_by("id")
        ],
    })


# ---------- SUMMARIZE (headings only) ----------
SUMMARY_SYSTEM = (
    "You are a study assistant. You are given the section headings of a student's "
    "notes. Write concise revision notes: a 2-3 sentence overview, then short "
    "bullet points grouped by topic. Do not invent details beyond what the headings imply."
)


@api_view(["POST"])
def summarize(request):
    doc_id = request.data.get("doc_id")
    try:
        doc = Document.objects.get(id=doc_id, user=request.user)
    except (Document.DoesNotExist, ValueError, TypeError):
        return Response({"error": "document not found"}, status=404)

    headings = rag.get_headings(request.user.id, doc.id)[:MAX_HEADINGS]
    content = "Section headings:\n" + "\n".join(f"- {h}" for h in headings)

    # Fallback: if headings are too poor, add a few top chunks (never the whole doc)
    if len(headings) < 4:
        extra = rag.search(request.user.id, "main topics and key concepts",
                           doc_id=doc.id, k=3)
        content += "\n\nSample excerpts:\n" + "\n\n".join(c["text"] for c in extra)

    try:
        summary = llm.chat(
            SUMMARY_SYSTEM,
            [{"role": "user", "content": content}],
            max_tokens=700,
        )
    except Exception as e:
        return Response({"error": f"LLM error: {e}"}, status=500)
    return Response({"summary": summary, "source": doc.name})


# ---------- MCQs ----------
MCQ_SYSTEM = (
    "You create multiple-choice questions from study notes. Return ONLY a JSON array, "
    "no markdown, no extra text. Each item must be: "
    '{"question": str, "options": [4 strings], "answer": int (0-3 index of correct option), '
    '"topic": str, "explanation": str}.'
)


def _parse_mcqs(text):
    text = re.sub(r"```(?:json)?", "", text).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("no JSON found")
    data = json.loads(text[start:end + 1])
    clean = []
    for q in data:
        opts = q.get("options")
        ans = q.get("answer")
        if (isinstance(q.get("question"), str) and isinstance(opts, list)
                and len(opts) == 4 and isinstance(ans, int) and 0 <= ans <= 3):
            clean.append({
                "question": q["question"],
                "options": [str(o) for o in opts],
                "answer": ans,
                "topic": str(q.get("topic", "General")),
                "explanation": str(q.get("explanation", "")),
            })
    return clean


def generate_mcqs_for(user_id, doc_id, count):
    """Reusable by the agent later. Sends only 1 chunk per chosen topic."""
    count = max(1, min(int(count), MAX_MCQ))
    headings = rag.get_headings(user_id, doc_id)
    topics = random.sample(headings, min(count, len(headings))) if headings else []
    chunks = []
    for t in topics:
        chunks += rag.search(user_id, t, doc_id=doc_id, k=1)
    if not chunks:
        chunks = rag.search(user_id, "key concepts", doc_id=doc_id, k=3)
    context = "\n\n".join(f"[Topic: {c['heading']}]\n{c['text']}" for c in chunks)
    prompt = f"Create {count} MCQs from these notes:\n\n{context}"
    text = llm.chat(MCQ_SYSTEM, [{"role": "user", "content": prompt}], max_tokens=1800)
    return _parse_mcqs(text)[:count]


@api_view(["POST"])
def mcqs(request):
    doc_id = request.data.get("doc_id")
    count = request.data.get("count", 5)
    try:
        Document.objects.get(id=doc_id, user=request.user)
    except (Document.DoesNotExist, ValueError, TypeError):
        return Response({"error": "document not found"}, status=404)
    try:
        questions = generate_mcqs_for(request.user.id, int(doc_id), count)
    except Exception as e:
        return Response({"error": f"Could not generate MCQs: {e}"}, status=500)
    return Response({"questions": questions})