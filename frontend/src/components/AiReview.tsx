import { useEffect, useState, type ReactNode } from "react";
import { api, type SavedReview } from "../api";
import { monthLabel } from "../format";
import { useAsync } from "../hooks";
import { AiAsk } from "./AiAsk";

/**
 * The AI review for one month. The model runs on your PC, so this card has to
 * handle "PC is off" gracefully: it always shows the last saved review, and
 * only offers to generate a new one when the PC answers.
 */
export function AiReview({ month }: { month: string }) {
  const status = useAsync(api.aiStatus, []);
  const saved = useAsync(() => api.savedReview(month), [month]);
  const [review, setReview] = useState<SavedReview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"review" | "ask">("review");

  useEffect(() => {
    setReview(saved.data?.saved ?? null);
    setError(null);
  }, [saved.data]);

  const s = status.data;
  const online = !!s?.reachable && !!s.model;

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      setReview(await api.createReview(month));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  let statusLine: ReactNode = null;
  if (status.loading && !s) statusLine = <span className="subtle">Checking your PC…</span>;
  else if (s && !s.configured) {
    statusLine = <span className="subtle">Not set up yet. Add your PC's address in <a href="#/settings">Settings</a>.</span>;
  } else if (s && !s.reachable) {
    statusLine = <span className="ai-status offline">● PC offline. Turn it on (with Ollama running) to use the AI. Saved reviews still show below.</span>;
  } else if (s && !s.model) {
    statusLine = <span className="ai-status offline">● Ollama has no models. On the PC run: ollama pull qwen3:14b</span>;
  } else if (s) {
    statusLine = <span className="ai-status online">● PC online · {s.model}</span>;
  }

  return (
    <div className="card ai-card">
      <div className="card-head">
        <h2 className="card-title">AI analyst</h2>
        <span className="card-subtitle">Runs on your PC; your data stays private</span>
        <div className="card-action">
          {tab === "review" && online && (
            <button className="btn btn-small btn-primary" onClick={generate} disabled={busy}>
              {busy ? "Thinking…" : review ? "Write a new review" : "Review this month"}
            </button>
          )}
        </div>
      </div>

      <div className="ai-tabs">
        <div className="segmented" role="tablist" aria-label="AI analyst">
          <button role="tab" type="button" aria-pressed={tab === "review"} aria-selected={tab === "review"} onClick={() => setTab("review")}>
            Review of {monthLabel(month)}
          </button>
          <button role="tab" type="button" aria-pressed={tab === "ask"} aria-selected={tab === "ask"} onClick={() => setTab("ask")}>
            Ask a question
          </button>
        </div>
        <div className="ai-statusline">{statusLine}</div>
      </div>

      {tab === "ask" ? (
        <AiAsk online={online} />
      ) : (
        <>
      {busy && <p className="hint">Asking the model on your PC. This usually takes 5–30 seconds.</p>}
      {error && <p className="message error">{error}</p>}

      {review ? (
        <div className={`ai-review ${busy ? "refreshing" : ""}`}>
          <p className="ai-headline">{review.review.headline}</p>
          <div className="grid grid-2 ai-columns">
            <div>
              <h3 className="ai-heading">What stood out</h3>
              <ul>
                {review.review.observations.map((o, i) => <li key={i}>{o}</li>)}
              </ul>
            </div>
            {review.review.suggestions.length > 0 && (
              <div>
                <h3 className="ai-heading">Ideas</h3>
                <ul>
                  {review.review.suggestions.map((s, i) => <li key={i}>{s}</li>)}
                </ul>
              </div>
            )}
          </div>
          <p className="subtle ai-meta">
            Written {new Date(review.created_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
            {" "}by {review.model}. AI can make mistakes, and this isn't professional financial advice.
          </p>
          <details className="table-view">
            <summary>What the AI was shown</summary>
            <pre className="ai-facts">{review.facts}</pre>
          </details>
        </div>
      ) : (
        !busy && saved.data && (
          <p className="hint" style={{ margin: 0 }}>
            No review for {monthLabel(month)} yet.
            {online ? " Click “Review this month” to get one." : ""}
          </p>
        )
      )}
        </>
      )}
    </div>
  );
}
