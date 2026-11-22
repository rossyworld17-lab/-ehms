import React, { useEffect, useRef, useState } from "react";
import { post, get, label } from "../api";
import { useAuth } from "../state";
import { Button, Card, Loadable, Textarea, errText, useLoad } from "../ui";

type Msg = { role: "user" | "assistant"; text: string; meta?: any };

export default function Assistant() {
  const { hotel } = useAuth();
  const status = useLoad(() => get("/api/assistant/status"), []);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs.length]);
  const ask = async (question: string) => {
    if (!question.trim() || busy) return;
    setMsgs(m => [...m, { role: "user", text: question }]);
    setQ("");
    setBusy(true);
    try {
      const r = await post("/api/assistant/ask", { question, hotel_id: hotel!.id });
      setMsgs(m => [...m, { role: "assistant", text: r.answer, meta: r }]);
    } catch (e) {
      setMsgs(m => [...m, { role: "assistant", text: errText(e) }]);
    } finally { setBusy(false); }
  };
  return <div className="page">
    <div className="page-h"><div><h1>Ask EHMS</h1><p className="muted">Questions about your hotel's data — answered only from what your role may see</p></div></div>
    <Loadable state={status}>{s => <div className="assistant-layout">
      <Card className="chat">
        <div className="chat-log" aria-live="polite">
          {!msgs.length && <div className="chat-empty"><p>Try one of these:</p><div className="chips">{s.examples.map((e: string) => <button key={e} type="button" className="chip" onClick={() => ask(e)}>{e}</button>)}</div></div>}
          {msgs.map((m, i) => <div key={i} className={`bubble ${m.role}`}>
            {m.text.split("\n\n").map((p, j) => <p key={j}>{p}</p>)}
            {m.meta && <div className="bubble-meta">{m.meta.tools_used.length ? `Sources: ${m.meta.tools_used.map(label).join(", ")}` : ""}
              {m.meta.engine === "claude" ? " · AI model" : " · built-in"} · {m.meta.disclaimer}</div>}
          </div>)}
          {busy && <div className="bubble assistant muted">Looking that up…</div>}
          <div ref={end} />
        </div>
        <form className="chat-input" onSubmit={e => { e.preventDefault(); ask(q); }}>
          <Textarea rows={2} value={q} maxLength={1000} placeholder="Ask about occupancy, revenue, forecasts, stock, complaints, approvals…" aria-label="Your question"
            onChange={e => setQ(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(q); } }} />
          <Button type="submit" busy={busy} disabled={!q.trim()}>Ask</Button>
        </form>
      </Card>
      <Card title="What I can answer for you">
        <ul className="small">{s.topics.map((t: any) => <li key={t.name}>{t.description}</li>)}</ul>
        {s.unavailable.length > 0 && <><p className="muted small mt">Not available to your role:</p><ul className="small muted">{s.unavailable.map((t: any) => <li key={t.description}>{t.description}</li>)}</ul></>}
        <p className="muted small mt">The assistant reads data; it never approves, refunds, cancels or changes anything. Decisions stay with people, under the normal approval rules.
          {s.engine === "claude" ? " Answers are phrased by an AI model using only the figures returned for your role." : " Answers come from the built-in engine (no external AI service)."}</p>
      </Card>
    </div>}</Loadable>
  </div>;
}
