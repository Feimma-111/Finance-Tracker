import type { ReactNode } from "react";
import type { AiStatus, ReviewText } from "../api";
import type { AsyncState } from "../hooks";

// Pieces shared by the monthly AI review and the "AI on these categories" panel.

/** Can the model run right now? (PC reachable and a model installed.) */
export function isOnline(status?: AiStatus): boolean {
  return !!status?.reachable && !!status.model;
}

/** "● PC online · qwen3.5" or what to do about it. */
export function AiStatusLine({ status, offlineNote }: { status: AsyncState<AiStatus>; offlineNote?: string }) {
  const s = status.data;
  let line: ReactNode = null;
  if (status.loading && !s) line = <span className="subtle">Checking your PC…</span>;
  else if (s && !s.configured) {
    line = <span className="subtle">Not set up yet. Add your PC's address in <a href="#/settings">Settings</a>.</span>;
  } else if (s && !s.reachable) {
    line = <span className="ai-status offline">● PC offline. Turn it on (with Ollama running) to use the AI.{offlineNote ? ` ${offlineNote}` : ""}</span>;
  } else if (s && !s.model) {
    line = <span className="ai-status offline">● Ollama has no models. On the PC run: ollama pull qwen3:14b</span>;
  } else if (s) {
    line = <span className="ai-status online">● PC online · {s.model}</span>;
  }
  return <div className="ai-statusline">{line}</div>;
}

/** Headline, observations and ideas, plus who wrote it and what it was shown. */
export function ReviewBody({
  review,
  model,
  createdAt,
  facts,
}: {
  review: ReviewText;
  model: string;
  createdAt: string;
  facts: string;
}) {
  return (
    <>
      <p className="ai-headline">{review.headline}</p>
      <div className="grid grid-2 ai-columns">
        <div>
          <h3 className="ai-heading">What stood out</h3>
          <ul>
            {review.observations.map((o, i) => <li key={i}>{o}</li>)}
          </ul>
        </div>
        {review.suggestions.length > 0 && (
          <div>
            <h3 className="ai-heading">Ideas</h3>
            <ul>
              {review.suggestions.map((s, i) => <li key={i}>{s}</li>)}
            </ul>
          </div>
        )}
      </div>
      <p className="subtle ai-meta">
        Written {new Date(createdAt).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
        {" "}by {model}. AI can make mistakes, and this isn't professional financial advice.
      </p>
      <details className="table-view">
        <summary>What the AI was shown</summary>
        <pre className="ai-facts">{facts}</pre>
      </details>
    </>
  );
}
