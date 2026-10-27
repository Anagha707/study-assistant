import json
import re
from typing import List

from pydantic import BaseModel, Field, ValidationError

from . import rag, llm

MAX_STEPS = 6            # main run
ADAPT_MAX_STEPS = 3      # run after the quiz
MAX_OBS_CHARS = 3200     # max characters of a tool result fed back to the LLM
MAX_TOPICS = 30
WEAK_THRESHOLD = 0.6

_JUNK = ("mrcet", "year/", "lecture notes")
_SKIP = {"output", "example", "program", "syntax", "general", "index"}


# ---------------- argument validation (Pydantic) ----------------
class NoArgs(BaseModel):
    pass


class SearchArgs(BaseModel):
    query: str = Field(min_length=3, max_length=200)
    k: int = Field(default=3, ge=1, le=4)


class TopicsArgs(BaseModel):
    topics: List[str] = Field(min_length=1, max_length=8)


class QuizArgs(BaseModel):
    topics: List[str] = Field(min_length=1, max_length=10)
    count: int = Field(default=5, ge=1, le=10)


class AnswerArgs(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class FinishArgs(BaseModel):
    message: str = Field(min_length=1, max_length=3000)


# ---------------- prompts ----------------
SUMMARY_SYSTEM = (
    "You are a study assistant. Write concise revision notes from the given notes "
    "excerpts: a short overview, then bullet points grouped by topic. "
    "Explain concepts and key points. Skip raw code output listings and page numbers. "
    "Use ONLY the excerpts."
)

MCQ_SYSTEM = (
    "You create multiple-choice questions from study notes. Ask CONCEPTUAL questions: "
    "definitions, differences between things, what a short code snippet does, or when to "
    "use something. Do NOT ask about page numbers, built-in attribute listings such as "
    "dunder names, or trivia about output formatting. All 4 options must be plausible and "
    "only one correct. Return ONLY a JSON array, no markdown, no extra text. Each item "
    'must be: {"question": str, "options": [4 strings], "answer": int (0-3 index of '
    'correct option), "topic": str, "explanation": str}.'
)

AGENT_SYSTEM = """You are a study-assistant agent. On each turn choose exactly ONE tool.
Reply with ONLY a JSON object, no other text: {{"tool": "<name>", "args": {{...}}}}

Tools:
{tools}

Guidelines:
- Exam / test preparation request: list_topics -> summarize_topics -> generate_quiz. The run pauses after the quiz.
- For exam preparation pick 6-8 topics spread across DIFFERENT parts of the list_topics result (beginning, middle and end), covering the core areas (for example data types, loops, functions, lists/tuples/dictionaries, files/exceptions) when they appear. Never pick all topics from one area.
- Use generate_quiz with count 8 for exam preparation, using the same topics.
- Question about the notes: search_notes, then finish with an answer based ONLY on the excerpts (mention if the notes do not cover it).
- Question unrelated to the notes: answer_general.
- Do NOT generate a quiz unless the student mentions an exam, test, quiz or practice.
- Pick topic names exactly as shown in the list_topics result.
- Never repeat the same tool call with the same arguments."""


# ---------------- state ----------------
class State:
    def __init__(self, user_id, doc_id):
        self.user_id = user_id
        self.doc_id = doc_id
        self.summary = None
        self.quiz = None
        self.revision = []
        self.sources = []
        self.final = None
        self.done = False
        self.steps = []


# ---------------- helpers ----------------
def _parse_mcqs(text):
    text = re.sub(r"```(?:json)?", "", text).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("no JSON found")
    data = json.loads(text[start:end + 1])
    clean = []
    for q in data:
        opts, ans = q.get("options"), q.get("answer")
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


def _good_heading(h):
    hl = h.lower().strip()
    return (len(hl) >= 5 and not hl.endswith(":") and hl not in _SKIP
            and not any(j in hl for j in _JUNK))


def _clean(topics):
    return [t.strip()[:80] for t in topics if t and t.strip()]


def _usable(text):
    """Reject chunks that are mostly code output or index/number pages."""
    if "__" in text:
        return False
    compact = re.sub(r"\s", "", text)
    if not compact:
        return False
    letters = sum(ch.isalpha() for ch in compact)
    if letters / len(compact) < 0.6:
        return False
    if len(re.findall(r"\b\d{1,3}\b", text)) > 12:      # table of contents / index
        return False
    return True


def _add_source(state, c):
    s = {"doc": c["doc_name"], "page": c["page"]}
    if s not in state.sources:
        state.sources.append(s)


def _gather(state, topics):
    """One good chunk per topic. Never the whole document."""
    out, seen = [], set()
    for t in topics:
        cands = rag.search(state.user_id, t, state.doc_id, k=3)
        good = [c for c in cands if _usable(c["text"])]
        pick = (good or cands[:1])[:1]
        for c in pick:
            key = (c["doc_id"], c["page"], c["text"][:40])
            if key not in seen:
                seen.add(key)
                out.append((t, c))
                _add_source(state, c)
    return out


def _names(topics):
    return ", ".join(topics[:8])


# ---------------- tools: each returns (observation_for_LLM, note_for_UI) ----------------
def t_list_topics(state, a):
    heads, seen = [], set()
    for h in rag.get_headings(state.user_id, state.doc_id):
        if _good_heading(h) and h.lower() not in seen:
            seen.add(h.lower())
            heads.append(h)
    if not heads:
        return "No clear headings found. Use search_notes instead.", "No clear topics found"
    if len(heads) > MAX_TOPICS:
        step = len(heads) / MAX_TOPICS               # evenly spaced across the whole document
        heads = [heads[int(i * step)] for i in range(MAX_TOPICS)]
    return "Topics (in document order): " + " | ".join(heads), f"Found {len(heads)} topics in the notes"


def t_search(state, a):
    chunks = rag.search(state.user_id, a.query, state.doc_id, k=a.k)
    if not chunks:
        return "Nothing relevant found in the notes.", "No relevant notes found"
    for c in chunks:
        _add_source(state, c)
    text = "\n\n".join(f"[{c['doc_name']} p{c['page']}] {c['text']}" for c in chunks)
    return text, f"Found {len(chunks)} relevant excerpts"


def t_summarize(state, a):
    topics = _clean(a.topics)
    pairs = _gather(state, topics)
    if not pairs:
        return "No matching notes found for those topics.", "No matching notes"
    ctx = "\n\n".join(f"[Topic: {t}]\n{c['text']}" for t, c in pairs)
    state.summary = llm.chat(SUMMARY_SYSTEM, [{"role": "user", "content": ctx}], max_tokens=700)
    return (f"Revision notes written for {len(pairs)} topics and shown to the student.",
            f"Wrote revision notes for {len(pairs)} topics: {_names(topics)}")


def t_quiz(state, a):
    topics = _clean(a.topics)
    pairs = _gather(state, topics)
    if not pairs:
        return "No matching notes found for those topics.", "No matching notes"
    ctx = "\n\n".join(f"[Topic: {t}]\n{c['text']}" for t, c in pairs)
    prompt = (f"Create exactly {a.count} MCQs. Use these exact topic names in the "
              f"'topic' field: {', '.join(topics)}.\n\nNotes:\n{ctx}")
    text = llm.chat(MCQ_SYSTEM, [{"role": "user", "content": prompt}], max_tokens=2200)
    try:
        qs = _parse_mcqs(text)[:a.count]
    except Exception:
        qs = []
    if not qs:
        return "Quiz generation failed. Try fewer topics.", "Quiz generation failed"
    state.quiz = qs
    return (f"Quiz with {len(qs)} questions created and shown to the student.",
            f"Created a {len(qs)}-question quiz on: {_names(topics)}")


def t_revision(state, a):
    metas = rag._col.get(where=rag._where(state.user_id, state.doc_id),
                         include=["metadatas"])["metadatas"]
    found = 0
    for t in _clean(a.topics):
        tl = t.lower()
        pages = sorted({
            m["page"] for m in metas
            if len(m["heading"]) >= 4
            and (tl in m["heading"].lower() or m["heading"].lower() in tl)
        })
        if not pages:  # fallback: semantic search
            pages = sorted({c["page"] for c in rag.search(state.user_id, t, state.doc_id, k=2)})
        if pages:
            state.revision.append({"topic": t, "pages": pages[:8]})
            found += 1
    if not found:
        return "Could not find pages for those topics.", "No pages found"
    return (f"Revision pointers for {found} topics shown to the student.",
            f"Pointed to pages for {found} topics")


def t_general(state, a):
    ans = llm.chat("You are a helpful tutor. Answer clearly and concisely.",
                   [{"role": "user", "content": a.question}], max_tokens=500)
    state.final = "⚠️ *Not from your notes (general knowledge)*\n\n" + ans
    state.done = True
    return "Answered from general knowledge.", "Answered from general knowledge"


def t_finish(state, a):
    state.final = a.message
    state.done = True
    return "Finished.", "Wrote the final answer"


TOOLS = {
    "list_topics": (NoArgs, t_list_topics,
                    'args {} - list the topic headings found in the student\'s notes.'),
    "search_notes": (SearchArgs, t_search,
                     'args {"query": str, "k": 1-4} - fetch the most relevant note excerpts.'),
    "summarize_topics": (TopicsArgs, t_summarize,
                         'args {"topics": [str]} - write revision notes for up to 8 topics.'),
    "generate_quiz": (QuizArgs, t_quiz,
                      'args {"topics": [str], "count": 1-10} - create MCQs. The run pauses so the student can answer.'),
    "recommend_revision": (TopicsArgs, t_revision,
                           'args {"topics": [str]} - show which pages of the notes to revise.'),
    "answer_general": (AnswerArgs, t_general,
                       'args {"question": str} - answer a question unrelated to the notes. Ends the run.'),
    "finish": (FinishArgs, t_finish,
               'args {"message": str} - give the final reply in markdown and stop.'),
}
MAIN_TOOLS = list(TOOLS)
ADAPT_TOOLS = ["generate_quiz", "recommend_revision", "finish"]


# ---------------- the agent loop ----------------
def _parse_call(raw):
    raw = re.sub(r"```(?:json)?", "", raw).strip()
    s, e = raw.find("{"), raw.rfind("}")
    if s == -1 or e == -1:
        return None
    try:
        data = json.loads(raw[s:e + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "tool" not in data:
        return None
    if not isinstance(data.get("args"), dict):
        data["args"] = {}
    return data


def run_agent(user_id, doc_id, request_text, mode="main"):
    state = State(user_id, doc_id)
    names = ADAPT_TOOLS if mode == "adapt" else MAIN_TOOLS
    max_steps = ADAPT_MAX_STEPS if mode == "adapt" else MAX_STEPS
    tool_help = "\n".join(f"- {n}: {TOOLS[n][2]}" for n in names)
    system = AGENT_SYSTEM.format(tools=tool_help)

    log, seen_calls = [], set()
    for step in range(1, max_steps + 1):
        progress = "\n".join(log) if log else "(nothing yet)"
        prompt = (f"Student request: {request_text}\n\n"
                  f"Progress so far:\n{progress}\n\nChoose the next tool.")
        raw = llm.chat(system, [{"role": "user", "content": prompt}], max_tokens=700)
        call = _parse_call(raw)

        if not call or call["tool"] not in names:
            log.append(f"Step {step}: invalid reply. Reply with valid JSON using one of: {', '.join(names)}.")
            state.steps.append({"tool": "invalid", "note": "Model reply was invalid, retrying"})
            continue

        name, args_raw = call["tool"], call["args"]
        key = name + json.dumps(args_raw, sort_keys=True, default=str)
        if key in seen_calls:
            log.append(f"Step {step}: you already did that. Choose a different tool or finish.")
            state.steps.append({"tool": name, "note": "Repeated call blocked"})
            continue
        seen_calls.add(key)

        model, fn, _ = TOOLS[name]
        try:
            args = model(**args_raw)
        except ValidationError as err:
            msg = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in err.errors())
            log.append(f"Step {step}: {name} rejected, invalid arguments ({msg})")
            state.steps.append({"tool": name, "note": "Invalid arguments rejected"})
            continue

        obs, note = fn(state, args)
        state.steps.append({"tool": name, "note": note})
        log.append(f"Step {step}: {name} -> {obs[:MAX_OBS_CHARS]}")

        if state.done or (name == "generate_quiz" and state.quiz):
            break
    return state


# ---------------- evaluate (plain Python, no LLM) ----------------
def evaluate(results):
    per = {}
    for r in results:
        t = str(r.get("topic", "General"))[:80]
        d = per.setdefault(t, [0, 0])
        d[1] += 1
        d[0] += 1 if r.get("correct") else 0
    total = sum(v[1] for v in per.values())
    correct = sum(v[0] for v in per.values())
    weak = [t for t, (c, n) in per.items() if c / n < WEAK_THRESHOLD]
    return {
        "score": correct, "total": total, "weak": weak,
        "per_topic": {t: {"correct": c, "total": n} for t, (c, n) in per.items()},
    }


def adapt_prompt(ev):
    lines = ", ".join(f"{t}: {v['correct']}/{v['total']}" for t, v in ev["per_topic"].items())
    return (f"The student finished the quiz. Score {ev['score']}/{ev['total']}. "
            f"Per topic: {lines}. Weak topics: {', '.join(ev['weak'])}. "
            "Decide the next step: recommend_revision for the weak topics, and/or "
            "generate_quiz (3-5 questions) on only the weak topics. Then stop.")


# ---------------- build the response ----------------
def build_reply(state):
    parts = []
    if state.final:
        parts.append(state.final)
    if state.summary:
        parts.append("## Revision notes\n\n" + state.summary)
    if state.revision:
        lines = ["## Revise these topics"] + [
            f"- **{r['topic']}**: pages {', '.join(map(str, r['pages']))}" for r in state.revision
        ]
        parts.append("\n".join(lines))
    if state.quiz:
        parts.append(f"I prepared a {len(state.quiz)}-question quiz. "
                     "Answer it below and I'll adapt your plan to your weak topics.")
    if not parts:
        parts.append("I couldn't complete that. Try rephrasing, or check that a document is indexed.")
    return "\n\n".join(parts)


def to_response(state):
    return {
        "steps": state.steps,
        "reply": build_reply(state),
        "quiz": state.quiz,
        "sources": state.sources,
    }