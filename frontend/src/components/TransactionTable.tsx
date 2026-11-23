import { useState } from "react";
import { api, type Transaction } from "../api";
import { dateLabel, money } from "../format";

export function TransactionTable({
  items,
  onChanged,
  compact = false,
}: {
  items: Transaction[];
  onChanged: () => void;
  compact?: boolean;
}) {
  const [confirming, setConfirming] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!items.length) return <p className="empty">No transactions yet.</p>;

  async function remove(id: number) {
    setError(null);
    try {
      await api.deleteTransaction(id);
      setConfirming(null);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="table-wrap">
      {error && <p className="message error">{error}</p>}
      <table>
        <thead>
          <tr>
            <th className="hide-narrow">Date</th>
            <th>Description</th>
            <th className="hide-narrow">Category</th>
            <th className="right">Amount</th>
            {!compact && <th aria-label="Actions" />}
          </tr>
        </thead>
        <tbody>
          {items.map((tx) => (
            <tr key={tx.id}>
              <td className="num hide-narrow" style={{ whiteSpace: "nowrap" }}>{dateLabel(tx.occurred_on)}</td>
              <td>
                {tx.description}
                {tx.recurring_id !== null && (
                  <span className="recurring-mark" title="Added automatically by a recurring rule"> ↻</span>
                )}
                {/* Phones: date and category move under the description, like Wallet. */}
                <span className="subtle show-narrow-block">{tx.category} · {dateLabel(tx.occurred_on)}</span>
              </td>
              <td className="subtle hide-narrow">{tx.category}</td>
              <td className={`right num ${tx.kind === "income" ? "amount-income" : ""}`} style={{ whiteSpace: "nowrap" }}>
                {tx.kind === "income" ? "+" : "−"}
                {money(tx.amount_cents)}
              </td>
              {!compact && (
                <td>
                  <div className="row-actions">
                    {confirming === tx.id ? (
                      <>
                        <span className="subtle">Delete for good?</span>
                        <button className="btn btn-small btn-danger" onClick={() => remove(tx.id)}>Delete</button>
                        <button className="btn btn-small" onClick={() => setConfirming(null)}>Cancel</button>
                      </>
                    ) : (
                      <button className="btn btn-small" onClick={() => setConfirming(tx.id)} aria-label={`Delete ${tx.description}`}>
                        Delete
                      </button>
                    )}
                  </div>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
