import { useState, useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "./api";
import AgentPage from "./AgentPage";

const NAV = [
  ["home", "🏠", "Home"],
  ["agent", "🤖", "Study Agent"],
  ["docs", "📄", "My Documents"],
  ["chat", "💬", "Chat"],
  ["summarize", "📝", "Summarize"],
  ["mcq", "❓", "MCQs"],
  ["history", "🕘", "Chat History"],
];

function useDocs() {
  const [docs, setDocs] = useState([]);
  useEffect(() => {
    api("/documents/").then((d) => setDocs(d.filter((x) => x.status === "indexed"))).catch(() => {});
  }, []);
  return docs;
}

/* ---------------- AUTH ---------------- */
function Auth({ onLogin }) {
  const [mode, setMode] = useState("login");
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    try {
      const d = await api(mode === "login" ? "/login/" : "/register/", {
        method: "POST",
        body: { username: u, password: p },
      });
      localStorage.setItem("token", d.token);
      localStorage.setItem("username", u);
      onLogin(u);
    } catch (e) {
      setErr(e.message);
    }
  };

  return (
    <div className="auth-wrap">
      <form className="auth-card" onSubmit={submit}>
        <div className="logo-big">🎓</div>
        <h2>Student AI Assistant</h2>
        <p className="muted">{mode === "login" ? "Log in to continue" : "Create your account"}</p>
        <input placeholder="Username" value={u} onChange={(e) => setU(e.target.value)} />
        <input type="password" placeholder="Password" value={p} onChange={(e) => setP(e.target.value)} />
        {err && <div className="error">{err}</div>}
        <button className="btn" type="submit">{mode === "login" ? "Login" : "Register"}</button>
        <p className="muted link" onClick={() => setMode(mode === "login" ? "register" : "login")}>
          {mode === "login" ? "No account? Register" : "Have an account? Login"}
        </p>
      </form>
    </div>
  );
}

/* ---------------- HOME ---------------- */
function Home({ go }) {
  const cards = [
    ["agent", "🤖", "Study Agent", "Prepare for an exam in one message"],
    ["docs", "📄", "Upload Documents", "Add your PDFs or text files"],
    ["chat", "💬", "Ask Questions", "Get answers from your content"],
    ["summarize", "📝", "Summarize", "Create concise notes"],
    ["mcq", "❓", "Generate MCQs", "Practice with custom questions"],
  ];
  return (
    <div className="home">
      <div className="logo-big">🎓</div>
      <h1>Welcome to Student AI Assistant</h1>
      <p className="muted">Upload your study materials and get instant help with questions, summaries and practice questions.</p>
      <div className="cards">
        {cards.map(([k, ic, t, d]) => (
          <div className="card" key={k} onClick={() => go(k)}>
            <div className="card-ic">{ic}</div>
            <b>{t}</b>
            <span className="muted small">{d}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------------- DOCUMENTS ---------------- */
function Docs() {
  const [docs, setDocs] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const inputRef = useRef();

  const load = () => api("/documents/").then(setDocs).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);

  const upload = async (files) => {
    setBusy(true);
    setErr("");
    for (const f of files) {
      const fd = new FormData();
      fd.append("file", f);
      try { await api("/documents/", { method: "POST", form: fd }); }
      catch (e) { setErr(e.message); }
    }
    await load();
    setBusy(false);
  };

  const del = async (id) => {
    await api(`/documents/${id}/`, { method: "DELETE" });
    load();
  };

  return (
    <div>
      <h2>My Documents</h2>
      <p className="muted">Upload your study materials. Supported formats: PDF, TXT.</p>
      <div
        className="drop"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); upload(e.dataTransfer.files); }}
      >
        <div style={{ fontSize: 36 }}>☁️</div>
        <p>{busy ? "Uploading and indexing... (can take a minute)" : "Drag and drop files here or"}</p>
        <button className="btn" disabled={busy} onClick={() => inputRef.current.click()}>Choose Files</button>
        <input ref={inputRef} type="file" accept=".pdf,.txt" multiple hidden onChange={(e) => upload(e.target.files)} />
      </div>
      {err && <div className="error">{err}</div>}
      <div className="panel">
        <b>Uploaded Documents</b>
        {docs.length === 0 && <p className="muted">No documents yet.</p>}
        {docs.map((d) => (
          <div className="row" key={d.id}>
            <span className="file-ic">{d.name.toLowerCase().endsWith(".pdf") ? "📕" : "📄"}</span>
            <div style={{ flex: 1 }}>
              <div>{d.name}</div>
              <div className="muted small">
                {(d.size / 1024 / 1024).toFixed(2)} MB • {new Date(d.uploaded_at).toLocaleDateString()}
              </div>
            </div>
            <span className={`badge ${d.status}`}>{d.status}</span>
            <button className="link-btn" onClick={() => del(d.id)}>Delete</button>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------------- CHAT ---------------- */
function Chat({ convId, onNew }) {
  const docs = useDocs();
  const [cid, setCid] = useState(convId);
  const [msgs, setMsgs] = useState([]);
  const [input, setInput] = useState("");
  const [docId, setDocId] = useState("");
  const [loading, setLoading] = useState(false);
  const bottom = useRef();

  useEffect(() => {
    if (convId) api(`/conversations/${convId}/`).then((d) => setMsgs(d.messages)).catch(() => {});
  }, [convId]);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, loading]);

  const send = async () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setMsgs((m) => [...m, { role: "user", content: text }]);
    setLoading(true);
    try {
      const d = await api("/chat/", {
        method: "POST",
        body: { message: text, doc_id: docId || null, conversation_id: cid },
      });
      setCid(d.conversation_id);
      setMsgs((m) => [...m, { role: "assistant", content: d.answer, sources: d.sources }]);
    } catch (e) {
      setMsgs((m) => [...m, { role: "assistant", content: "⚠️ " + e.message, sources: [] }]);
    }
    setLoading(false);
  };

  return (
    <div className="chat">
      <div className="chat-head">
        <div>
          <h2>Chat with Your Documents</h2>
          <p className="muted">Ask questions based on your uploaded study materials.</p>
        </div>
        <div className="chat-tools">
          <select value={docId} onChange={(e) => setDocId(e.target.value)}>
            <option value="">All documents</option>
            {docs.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
          <button className="btn-outline" onClick={onNew}>New chat</button>
        </div>
      </div>
      <div className="msgs">
        {msgs.length === 0 && <p className="muted">Try: "What is the difference between a list and a tuple?"</p>}
        {msgs.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>
            {m.role === "assistant" ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
            ) : m.content}
            {m.sources?.length > 0 && (
              <div className="sources">
                {m.sources.map((s, j) => (
                  <span key={j}>📎 {s.doc} (Page {s.page})</span>
                ))}
              </div>
            )}
          </div>
        ))}
        {loading && <div className="bubble assistant muted">Thinking...</div>}
        <div ref={bottom} />
      </div>
      <div className="inputbar">
        <input
          placeholder="Type your message..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button className="btn" onClick={send}>Send</button>
      </div>
    </div>
  );
}

/* ---------------- SUMMARIZE ---------------- */
function Summarize() {
  const docs = useDocs();
  const [docId, setDocId] = useState("");
  const [res, setRes] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const run = async () => {
    if (!docId) return setErr("Select a document first");
    setErr(""); setRes(null); setLoading(true);
    try { setRes(await api("/summarize/", { method: "POST", body: { doc_id: docId } })); }
    catch (e) { setErr(e.message); }
    setLoading(false);
  };

  return (
    <div>
      <h2>Generate Summary</h2>
      <p className="muted">Select a document and get a concise summary.</p>
      <select className="full" value={docId} onChange={(e) => setDocId(e.target.value)}>
        <option value="">Select a document</option>
        {docs.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
      </select>
      <button className="btn" onClick={run} disabled={loading}>{loading ? "Generating..." : "Generate Summary"}</button>
      {err && <div className="error">{err}</div>}
      {res && (
        <div className="summary">
          <b>Summary</b>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{res.summary}</ReactMarkdown>
          <div className="row-between">
            <span className="muted small">Source: {res.source}</span>
            <button className="btn-outline" onClick={() => navigator.clipboard.writeText(res.summary)}>Copy</button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------------- MCQs ---------------- */
function MCQs() {
  const docs = useDocs();
  const [docId, setDocId] = useState("");
  const [count, setCount] = useState(5);
  const [qs, setQs] = useState([]);
  const [idx, setIdx] = useState(0);
  const [picked, setPicked] = useState(null);
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const gen = async () => {
    if (!docId) return setErr("Select a document first");
    setErr(""); setQs([]); setIdx(0); setPicked(null); setResults([]); setLoading(true);
    try {
      const d = await api("/mcqs/", { method: "POST", body: { doc_id: docId, count } });
      setQs(d.questions);
    } catch (e) { setErr(e.message); }
    setLoading(false);
  };

  const pick = (i) => {
    if (picked !== null) return;
    setPicked(i);
    setResults((r) => [...r, { topic: qs[idx].topic, correct: i === qs[idx].answer }]);
  };
  const next = () => { setIdx(idx + 1); setPicked(null); };

  const done = qs.length > 0 && idx >= qs.length;
  const score = results.filter((r) => r.correct).length;
  const weak = [...new Set(results.filter((r) => !r.correct).map((r) => r.topic))];

  return (
    <div>
      <h2>Generate Practice Questions</h2>
      <p className="muted">Select a document and choose the number of questions.</p>
      <select className="full" value={docId} onChange={(e) => setDocId(e.target.value)}>
        <option value="">Select a document</option>
        {docs.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
      </select>
      <div className="inline">
        <label>Number of Questions:</label>
        <select value={count} onChange={(e) => setCount(Number(e.target.value))}>
          {[3, 5, 8, 10].map((n) => <option key={n}>{n}</option>)}
        </select>
        <button className="btn" onClick={gen} disabled={loading}>{loading ? "Generating..." : "Generate MCQs"}</button>
      </div>
      {err && <div className="error">{err}</div>}

      {qs.length > 0 && !done && (
        <div className="panel">
          <p className="muted small">Question {idx + 1} of {qs.length}</p>
          <b>{idx + 1}. {qs[idx].question}</b>
          {qs[idx].options.map((o, i) => {
            let cls = "opt";
            if (picked !== null) {
              if (i === qs[idx].answer) cls += " right";
              else if (i === picked) cls += " wrong";
            }
            return <div key={i} className={cls} onClick={() => pick(i)}>{o}</div>;
          })}
          {picked !== null && (
            <>
              <p className="muted small">{qs[idx].explanation}</p>
              <div className="right-align">
                <button className="btn" onClick={next}>{idx + 1 === qs.length ? "Finish" : "Next"}</button>
              </div>
            </>
          )}
        </div>
      )}

      {done && (
        <div className="panel">
          <h3>Your score: {score} / {qs.length}</h3>
          {weak.length ? (
            <p>Weak topics to revise: <b>{weak.join(", ")}</b></p>
          ) : (
            <p>Perfect score. No weak topics! 🎉</p>
          )}
          <button className="btn" onClick={gen}>Try new questions</button>
        </div>
      )}
    </div>
  );
}

/* ---------------- HISTORY ---------------- */
function History({ onOpen }) {
  const [list, setList] = useState([]);
  const load = () => api("/conversations/").then(setList).catch(() => {});
  useEffect(() => { load(); }, []);
  const del = async (e, id) => {
    e.stopPropagation();
    await api(`/conversations/${id}/`, { method: "DELETE" });
    load();
  };
  return (
    <div>
      <h2>Chat History</h2>
      <p className="muted">View your previous conversations.</p>
      <div className="panel">
        {list.length === 0 && <p className="muted">No conversations yet.</p>}
        {list.map((c) => (
          <div className="row clickable" key={c.id} onClick={() => onOpen(c.id)}>
            <span className="file-ic">💬</span>
            <div style={{ flex: 1 }}>
              <div>{c.title}</div>
              <div className="muted small">{c.preview.slice(0, 80)}</div>
            </div>
            <span className="muted small">{new Date(c.created_at).toLocaleString()}</span>
            <button className="link-btn" onClick={(e) => del(e, c.id)}>Delete</button>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------------- APP SHELL ---------------- */
export default function App() {
  const [user, setUser] = useState(localStorage.getItem("token") ? localStorage.getItem("username") : null);
  const [page, setPage] = useState("home");
  const [openConv, setOpenConv] = useState(null);
  const [chatKey, setChatKey] = useState(0);

  if (!user) return <Auth onLogin={setUser} />;

  const logout = () => { localStorage.clear(); setUser(null); };
  const openChat = (id) => { setOpenConv(id); setChatKey((k) => k + 1); setPage("chat"); };
  const newChat = () => { setOpenConv(null); setChatKey((k) => k + 1); };

  return (
    <div className="app">
      <aside className="side">
        <div className="brand">🎓 Student AI Assistant</div>
        {NAV.map(([k, ic, label]) => (
          <div key={k} className={`nav ${page === k ? "active" : ""}`} onClick={() => setPage(k)}>
            <span>{ic}</span> {label}
          </div>
        ))}
        <div className="nav logout" onClick={logout}>⏻ Logout</div>
      </aside>
      <main className="main">
        <div className="topbar"><span className="user">👤 {user}</span></div>
        <div className="content">
          {page === "home" && <Home go={setPage} />}
          {page === "agent" && <AgentPage />}
          {page === "docs" && <Docs />}
          {page === "chat" && <Chat key={chatKey} convId={openConv} onNew={newChat} />}
          {page === "summarize" && <Summarize />}
          {page === "mcq" && <MCQs />}
          {page === "history" && <History onOpen={openChat} />}
        </div>
      </main>
    </div>
  );
}