import { useEffect, useRef, useState, type FormEvent } from "react";
import { clearChat, sendQuestion, useChat, type ChatMessage } from "../chatStore";

const SUGGESTIONS = [
  "How much did I spend on food since August?",
  "What were my 5 biggest purchases this month?",
  "Did I spend more on groceries this month or last month?",
  "How much do my subscriptions cost per month?",
  "What's my average monthly spending?",
];

// Friendlier names for the lookup steps shown under each answer.
const TOOL_LABELS: Record<string, string> = {
  list_categories: "Listed your categories",
  spending_total: "Added up spending",
  income_total: "Added up income",
  spending_by_category: "Broke spending down by category",
  compare_spending: "Compared two periods",
  monthly_spending: "Totaled spending by month",
  find_transactions: "Looked up transactions",
  recurring_charges: "Checked recurring charges",
  net_worth_history: "Checked net worth history",
};

/** Models like to write **bold** and "*   item" lists; show them as bold and
    bullets (as React text, never as HTML). */
function withBold(text: string) {
  text = text.replace(/^[ \t]*[*-][ \t]+/gm, "• ");
  return text.split(/(\*\*[^*\n]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4
      ? <strong key={i}>{part.slice(2, -2)}</strong>
      : part,
  );
}

/**
 * Ask questions in plain English. The model on your PC answers by calling
 * read-only lookup tools; every number comes from those tools, and any number
 * that didn't is flagged. The conversation lives in chatStore: it survives
 * switching tabs and pages, and is gone when the browser tab closes.
 */
export function AiAsk({ online }: { online: boolean }) {
  const { messages, busy } = useChat();
  const [draft, setDraft] = useState("");

  function send(question: string) {
    if (!question.trim() || busy) return;
    setDraft("");
    sendQuestion(question);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    send(draft);
  }

  return (
    <div className="ask">
      {messages.length === 0 ? (
        <div className="ask-empty">
          <p className="hint" style={{ margin: "0 0 10px" }}>
            Ask anything about your spending, income, recurring charges, or net worth. The AI looks up the exact
            numbers in your data, and you can see every lookup it made.
          </p>
          <div className="chips">
            {SUGGESTIONS.map((s) => (
              <button key={s} type="button" className="chip" disabled={!online} onClick={() => send(s)}>
                {s}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <ChatThread messages={messages} busy={busy} />
      )}

      <form className="inline-form ask-form" onSubmit={submit}>
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={online ? "Ask about your money…" : "Your PC needs to be on to answer questions"}
          disabled={!online}
          maxLength={500}
          aria-label="Question"
        />
        <button className="btn btn-primary" type="submit" disabled={!online || busy || !draft.trim()}>
          {busy ? "Asking…" : "Ask"}
        </button>
        {messages.length > 0 && (
          <button className="btn" type="button" onClick={clearChat} disabled={busy}>
            Clear
          </button>
        )}
      </form>
      <p className="subtle" style={{ margin: "8px 0 0" }}>
        This conversation stays until you close the browser tab; it isn't saved. AI can make mistakes, and this
        isn't professional financial advice.
      </p>
    </div>
  );
}

/**
 * A conversation: questions on the right, answers on the left, each answer
 * with a warning for any number the app didn't compute and the lookups it made.
 */
export function ChatThread({ messages, busy }: { messages: ChatMessage[]; busy: boolean }) {
  const thread = useRef<HTMLDivElement>(null);

  // Keep the newest message in view (scrolls only the chat box, not the page).
  useEffect(() => {
    const box = thread.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [messages, busy]);

  return (
    <div className="ask-thread" aria-live="polite" ref={thread}>
      {messages.map((m, i) =>
        m.role === "user" ? (
          <div key={i} className="ask-q">{m.content}</div>
        ) : (
          <div key={i} className={`ask-a ${m.error ? "error" : ""}`}>
            <div className="ask-text">{withBold(m.content)}</div>
            {m.result && m.result.unverified.length > 0 && (
              <p className="ask-warning">
                ⚠ {m.result.unverified.join(", ")} {m.result.unverified.length === 1 ? "wasn't" : "weren't"} calculated
                by the app. Double-check {m.result.unverified.length === 1 ? "it" : "them"}.
              </p>
            )}
            {m.result && m.result.steps.length > 0 && (
              <details className="table-view">
                <summary>How I got this ({m.result.steps.length} lookup{m.result.steps.length === 1 ? "" : "s"})</summary>
                <ol className="ask-steps">
                  {m.result.steps.map((step, j) => (
                    <li key={j}>
                      <strong>{TOOL_LABELS[step.tool] ?? step.tool}</strong>
                      {Object.keys(step.arguments).length > 0 && (
                        <span className="subtle">
                          {" "}({Object.entries(step.arguments).map(([k, v]) => `${k}: ${String(v)}`).join(", ")})
                        </span>
                      )}
                      <pre className="ai-facts">{JSON.stringify(step.result, null, 2)}</pre>
                    </li>
                  ))}
                </ol>
              </details>
            )}
          </div>
        ),
      )}
      {busy && <div className="ask-a subtle">Looking that up on your PC…</div>}
    </div>
  );
}
