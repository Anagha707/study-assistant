import { useState, useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "./api";
import "./agent.css";

const ICONS = {
  list_topics: "🔍", search_notes: "🔎", summarize_topics: "📝",
  generate_quiz: "❓", recommend_revision: "📌", answer_general: "💡",
  finish: "✅", evaluate: "📊", invalid: "⚠️",
};

const EXAMPLES = [
  "I have a Python exam tomorrow. Prepare me using my uploaded notes.",
  "What is recursion?",
  "Who won the cricket world cup?",
];

function Quiz({ quiz, onDone, disabled }) {
  const [idx, setIdx] = useState(0);
  const [picked, setPicked] = useState(null);
  const [results, setResults] = useState([]);
  const [sent, setSent] = useState(false);

  if (idx >= quiz.length) {
    const score = results.filter((r) => r.correct).length;
    return (
      <div className="agent-quiz">
        <b>Quiz finished: {score} / {quiz.length}</b>
        <div style={{ marginTop: 10 }}>
          <button
            className="btn"
            disabled={disabled || sent}
            onClick={() => { setSent(true); onDone(results); }}
          >
            {sent ? "Agent is adapting your plan..." : "Let the agent adapt my plan"}
          </button>
        </div>
      </div>
    );
  }

  const q = quiz[idx];
  const pick = (i) => {
    if (picked !== null) return;
    setPicked(i);
    setResults((r) => [...r, { topic: q.topic, correct: i === q.answer }]);
  };
  const next = () => { setIdx(idx + 1); setPicked(null); };

  return (
    <div className="agent-quiz">
      <p className="muted small">Question {idx + 1} of {quiz.length} • {q.topic}</p>
      <b>{idx + 1}. {q.question}</b>
      {q.options.map((o, i) => {
        let cls = "opt";
        if (picked !== null) {
          if (i === q.answer) cls += " right";
          else if (i === picked) cls += " wrong";
        }
        return <div key={i} className={cls} onClick={() => pick(i)}>{o}</div>;
      })}
      {picked !== null && (
        <>
          <p className="muted small">{q.explanation}</p>
          <div className="right-align">
            <button className="btn" onClick={next}>{idx + 1 === quiz.length ? "Finish" : "Next"}</button>
          </div>
        </>
      )}
    </div>
  );
}

export default function AgentPage() {
  const [docs, setDocs] = useState([]);
  const [docId, setDocId] = useState("");
  const [msgs, setMsgs] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottom = useRef();

  useEffect(() => {
    api("/documents/")
      .then((d) => setDocs(d.filter((x) => x.status === "indexed")))
      .catch(() => {});
  }, []);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, loading]);

  const addAgentMsg = (d) =>
    setMsgs((m) => [...m, { role: "agent", content: d.reply, steps: d.steps, quiz: d.quiz, sources: d.sources }]);
  const addError = (e) =>
    setMsgs((m) => [...m, { role: "agent", content: "⚠️ " + e.message, steps: [], quiz: null, sources: [] }]);

  const send = async (text) => {
    const t = (text ?? input).trim();
    if (!t || loading) return;
    setInput("");
    setMsgs((m) => [...m, { role: "user", content: t }]);
    setLoading(true);
    try {
      addAgentMsg(await api("/agent/", { method: "POST", body: { message: t, doc_id: docId || null } }));
    } catch (e) { addError(e); }
    setLoading(false);
  };

  const adapt = async (results) => {
    setLoading(true);
    try {
      addAgentMsg(await api("/agent/adapt/", { method: "POST", body: { results, doc_id: docId || null } }));
    } catch (e) { addError(e); }
    setLoading(false);
  };

  return (
    <div className="chat">
      <div className="chat-head">
        <div>
          <h2>🤖 Study Agent</h2>
          <p className="muted">Ask in one message. The agent plans, picks tools, and adapts to your quiz results.</p>
        </div>
        <div className="chat-tools">
          <select value={docId} onChange={(e) => setDocId(e.target.value)}>
            <option value="">All documents</option>
            {docs.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
          <button className="btn-outline" onClick={() => setMsgs([])}>Clear</button>
        </div>
      </div>

      <div className="msgs">
        {msgs.length === 0 && (
          <div>
            <p className="muted">Try one of these:</p>
            <div className="chips">
              {EXAMPLES.map((ex) => (
                <span key={ex} className="chip" onClick={() => send(ex)}>{ex}</span>
              ))}
            </div>
          </div>
        )}

        {msgs.map((m, i) => (
          <div key={i} className={`bubble ${m.role === "user" ? "user" : "assistant wide"}`}>
            {m.role === "agent" && m.steps?.length > 0 && (
              <div className="steps">
                <b>Agent steps</b>
                {m.steps.map((s, j) => (
                  <div className="step" key={j}>
                    {ICONS[s.tool] || "•"} <code>{s.tool}</code> {s.note}
                  </div>
                ))}
              </div>
            )}
            {m.role === "agent" ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
            ) : m.content}
            {m.sources?.length > 0 && (
              <div className="sources">
                {m.sources.map((s, j) => <span key={j}>📎 {s.doc} (Page {s.page})</span>)}
              </div>
            )}
            {m.quiz && <Quiz quiz={m.quiz} onDone={adapt} disabled={loading} />}
          </div>
        ))}

        {loading && (
          <div className="bubble assistant muted">
            Agent is working: searching, planning, using tools...
          </div>
        )}
        <div ref={bottom} />
      </div>

      <div className="inputbar">
        <input
          placeholder="e.g. I have a Python exam tomorrow. Prepare me."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button className="btn" onClick={() => send()} disabled={loading}>Send</button>
      </div>
    </div>
  );
}