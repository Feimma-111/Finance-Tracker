import { useEffect, useState } from "react";
import { api, type AiStatus, type SavedReview } from "../api";
import { monthLabel } from "../format";
import { useAsync, type AsyncState } from "../hooks";
import { AiAsk } from "./AiAsk";
import { AiStatusLine, isOnline, ReviewBody } from "./AiParts";
import { FollowUpChat, reviewText } from "./FollowUpChat";

const REVIEW_FOLLOW_UPS = [
  "Why was this month different?",
  "What changed most from last month?",
  "Which purchases could I cut first?",
];

/**
 * The AI review for one month. The model runs on your PC, so this card has to
 * handle "PC is off" gracefully: it always shows the last saved review, and
 * only offers to generate a new one when the PC answers.
 */
export function AiReview({ month, version, status }: { month: string; version: number; status: AsyncState<AiStatus> }) {
  // Reloads when data changes (version), so the "out of date" note appears right away.
  const saved = useAsync(() => api.savedReview(month), [month, version]);
  const [review, setReview] = useState<SavedReview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Remember the open tab for this browser session, like the chat itself.
  const [tab, setTabState] = useState<"review" | "ask">(() => {
    try {
      return sessionStorage.getItem("finance-tracker:ai-tab") === "ask" ? "ask" : "review";
    } catch {
      return "review";
    }
  });
  const setTab = (next: "review" | "ask") => {
    setTabState(next);
    try {
      sessionStorage.setItem("finance-tracker:ai-tab", next);
    } catch {
      // storage blocked; the tab just won't be remembered
    }
  };

  useEffect(() => {
    setReview(saved.data?.saved ?? null);
    setError(null);
  }, [saved.data]);

  const online = isOnline(status.data);

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
        <AiStatusLine status={status} offlineNote="Saved reviews still show below." />
      </div>

      {tab === "ask" ? (
        <AiAsk online={online} />
      ) : (
        <>
      {busy && <p className="hint">Asking the model on your PC. This usually takes 5–30 seconds.</p>}
      {error && <p className="message error">{error}</p>}

      {review ? (
        <div className={`ai-review ${busy ? "refreshing" : ""}`}>
          {review.outdated && (
            <div className="notice">
              <span>
                Your transactions or covered expenses changed after this review was written, so it may not
                reflect them.
              </span>
              {online && (
                <button className="btn btn-small" onClick={generate} disabled={busy}>Write a new review</button>
              )}
            </div>
          )}
          <ReviewBody review={review.review} model={review.model} createdAt={review.created_at} facts={review.facts} />
          <FollowUpChat
            chatKey={`review:${month}:${review.created_at}`}
            analysis={reviewText(review.review)}
            about={{ review_month: month }}
            online={online}
            suggestions={REVIEW_FOLLOW_UPS}
          />
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
