import { useState } from "react";
import { api, type RecurringRule } from "../api";
import { dateLabel, frequencyText, moneyIn } from "../format";
import { useAsync } from "../hooks";

/** Recurring rules with pause/resume, change amount, and delete. */
export function RecurringList({ version, onChanged }: { version: number; onChanged: () => void }) {
  const rules = useAsync(api.recurring, [version]);
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [confirming, setConfirming] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function act(work: () => Promise<unknown>) {
    setError(null);
    try {
      await work();
      setEditing(null);
      setConfirming(null);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (rules.error) return <p className="message error">{rules.error}</p>;
  if (!rules.data) return null;
  if (!rules.data.length) {
    return <p className="hint" style={{ margin: 0 }}>Nothing recurring yet. Pick a "Repeat" option when adding rent, subscriptions, or paychecks.</p>;
  }

  return (
    <div className="recurring-list">
      {error && <p className="message error">{error}</p>}
      {rules.data.map((rule: RecurringRule) => (
        <div key={rule.id} className={`recurring-item ${rule.active ? "" : "paused"}`}>
          <div className="recurring-main">
            <div>
              <strong>{rule.description}</strong> <span className="subtle">· {rule.category}</span>
            </div>
            <div className="subtle">
              {rule.active ? `Every ${frequencyText(rule.frequency).replace(/^every /, "")} · next ${dateLabel(rule.next_due)}` : "Paused"}
            </div>
          </div>
          <div className={`num recurring-amount ${rule.kind === "income" ? "amount-income" : ""}`}>
            {editing === rule.id ? (
              <input
                autoFocus
                onFocus={(e) => e.target.select()}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && act(() => api.updateRecurring(rule.id, { amount: draft }))}
                style={{ width: 96 }}
                aria-label="New amount"
              />
            ) : (
              <>{rule.kind === "income" ? "+" : "−"}{moneyIn(rule.amount_cents, rule.currency)}</>
            )}
          </div>
          <div className="row-actions">
            {editing === rule.id ? (
              <>
                <button className="btn btn-small btn-primary" onClick={() => act(() => api.updateRecurring(rule.id, { amount: draft }))}>Save</button>
                <button className="btn btn-small" onClick={() => setEditing(null)}>Cancel</button>
              </>
            ) : confirming === rule.id ? (
              <>
                <button className="btn btn-small btn-danger" onClick={() => act(() => api.deleteRecurring(rule.id))}>Stop</button>
                <button className="btn btn-small" onClick={() => setConfirming(null)}>Cancel</button>
              </>
            ) : (
              <>
                <button
                  className="btn btn-small"
                  onClick={() => {
                    setEditing(rule.id);
                    setConfirming(null);
                    setDraft((rule.amount_cents / 100).toFixed(2));
                  }}
                  aria-label={`Change amount of ${rule.description}`}
                >
                  Edit
                </button>
                <button className="btn btn-small" onClick={() => act(() => api.updateRecurring(rule.id, { active: !rule.active }))}>
                  {rule.active ? "Pause" : "Resume"}
                </button>
                <button className="btn btn-small" onClick={() => { setConfirming(rule.id); setEditing(null); }} aria-label={`Stop ${rule.description}`}>
                  ✕
                </button>
              </>
            )}
          </div>
          {confirming === rule.id && (
            <div className="hint recurring-note">Stops future payments. The ones already added stay in your history.</div>
          )}
        </div>
      ))}
    </div>
  );
}
