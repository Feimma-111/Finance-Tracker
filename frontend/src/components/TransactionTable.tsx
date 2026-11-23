import { useState, type FormEvent, type KeyboardEvent } from "react";
import { api, type Kind, type Transaction } from "../api";
import { dateLabel, money, todayIso } from "../format";
import { useAsync } from "../hooks";
import { Sheet } from "./Sheet";

/** Click (or press Enter on) a row to edit it; deleting lives in the edit sheet. */
export function TransactionTable({ items, onChanged }: { items: Transaction[]; onChanged: () => void }) {
  const [editing, setEditing] = useState<Transaction | null>(null);

  if (!items.length) return <p className="empty">No transactions yet.</p>;

  const open = (tx: Transaction) => setEditing(tx);
  const onKey = (event: KeyboardEvent, tx: Transaction) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      open(tx);
    }
  };

  return (
    <div className="table-wrap">
      <table className="clickable-rows">
        <thead>
          <tr>
            <th className="hide-narrow">Date</th>
            <th>Description</th>
            <th className="hide-narrow">Category</th>
            <th className="right">Amount</th>
          </tr>
        </thead>
        <tbody>
          {items.map((tx) => (
            <tr
              key={tx.id}
              tabIndex={0}
              role="button"
              aria-label={`Edit ${tx.description}, ${money(tx.amount_cents)} on ${dateLabel(tx.occurred_on)}`}
              onClick={() => open(tx)}
              onKeyDown={(e) => onKey(e, tx)}
            >
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
                <span className="row-chevron" aria-hidden="true">›</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {editing && (
        <EditTransactionSheet
          tx={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            onChanged();
          }}
        />
      )}
    </div>
  );
}

function EditTransactionSheet({ tx, onClose, onSaved }: { tx: Transaction; onClose: () => void; onSaved: () => void }) {
  const [kind, setKind] = useState<Kind>(tx.kind);
  const [description, setDescription] = useState(tx.description);
  const [amount, setAmount] = useState((tx.amount_cents / 100).toFixed(2));
  const [category, setCategory] = useState(tx.category);
  const [date, setDate] = useState(tx.occurred_on);
  const [applyToMatching, setApplyToMatching] = useState(true);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const details = useAsync(() => api.getTransaction(tx.id), [tx.id]);
  const categories = useAsync(() => api.categories(kind), [kind]);
  const matching = details.data?.matching ?? 0;
  const categoryChanged = category.trim().toLowerCase() !== tx.category.toLowerCase();

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.updateTransaction(tx.id, {
        kind, description, amount, category, occurred_on: date,
        apply_category_to_matching: categoryChanged && matching > 0 && applyToMatching,
      });
      onSaved();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await api.deleteTransaction(tx.id);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <Sheet title="Edit transaction" onClose={onClose}>
      <form className="form" onSubmit={save}>
        <div className="segmented" role="group" aria-label="Transaction type">
          {(["expense", "income"] as Kind[]).map((k) => (
            <button key={k} type="button" aria-pressed={kind === k} onClick={() => setKind(k)}>
              {k === "expense" ? "Expense" : "Income"}
            </button>
          ))}
        </div>
        <label className="field">
          <span>Description</span>
          <input type="text" value={description} onChange={(e) => setDescription(e.target.value)} required />
        </label>
        <div className="field-row">
          <label className="field">
            <span>Amount</span>
            <div className="money-input">
              <i>$</i>
              <input type="text" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} required />
            </div>
          </label>
          <label className="field">
            <span>Date</span>
            <input type="date" value={date} max={todayIso()} onChange={(e) => setDate(e.target.value)} required />
          </label>
        </div>
        <label className="field">
          <span>Category</span>
          <input type="text" list="edit-categories" value={category} onChange={(e) => setCategory(e.target.value)} required />
          <datalist id="edit-categories">
            {categories.data?.map((c) => <option key={c} value={c} />)}
          </datalist>
        </label>
        {categoryChanged && matching > 0 && (
          <label className="check-row">
            <input type="checkbox" checked={applyToMatching} onChange={(e) => setApplyToMatching(e.target.checked)} />
            Also move {matching} other “{tx.description}” transaction{matching === 1 ? "" : "s"} to this category
          </label>
        )}
        {tx.recurring_id !== null && (
          <p className="hint" style={{ margin: 0 }}>
            A recurring rule added this. Changes here apply to this one only; edit the rule on the Transactions page.
          </p>
        )}
        {error && <p className="message error" style={{ margin: 0 }}>{error}</p>}
        <button className="btn btn-primary" type="submit" disabled={busy}>Save</button>
        <div className="sheet-danger">
          {confirmDelete ? (
            <>
              <span className="subtle">Delete for good? This can't be undone.</span>
              <button type="button" className="btn btn-small btn-danger" onClick={remove} disabled={busy}>Delete</button>
              <button type="button" className="btn btn-small" onClick={() => setConfirmDelete(false)}>Keep</button>
            </>
          ) : (
            <button type="button" className="btn-link danger-link" onClick={() => setConfirmDelete(true)}>
              Delete transaction
            </button>
          )}
        </div>
      </form>
    </Sheet>
  );
}
