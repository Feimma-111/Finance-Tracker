import { Fragment, useState, type FormEvent, type KeyboardEvent } from "react";
import { api, type Frequency, type Kind, type Transaction } from "../api";
import { currencySymbol, dateLabel, displayCurrency, FREQUENCIES, frequencyText, money, moneyIn, monthLabel, todayIso } from "../format";
import { useAsync } from "../hooks";
import { CategoryIcon } from "../icons";
import { AccountField, useCashAccounts } from "./AccountField";
import { Sheet } from "./Sheet";
import { DateInput } from "./DateInput";

/**
 * Transactions grouped under day headings ("Today", "Yesterday", "Tue, Nov 18"),
 * each with its category icon. Click (or press Enter on) a row to edit it.
 */
export function TransactionList({
  items,
  onChanged,
  emptyText = "No transactions yet.",
}: {
  items: Transaction[];
  onChanged: () => void;
  emptyText?: string;
}) {
  const [editing, setEditing] = useState<Transaction | null>(null);

  if (!items.length) return <p className="empty">{emptyText}</p>;

  // Items arrive newest first; group consecutive ones by date.
  const groups: { day: string; items: Transaction[]; net: number }[] = [];
  for (const tx of items) {
    const last = groups[groups.length - 1];
    const signed = tx.kind === "income" ? tx.amount_cents : -tx.amount_cents;
    if (last && last.day === tx.occurred_on) {
      last.items.push(tx);
      last.net += signed;
    } else {
      groups.push({ day: tx.occurred_on, items: [tx], net: signed });
    }
  }

  const onKey = (event: KeyboardEvent, tx: Transaction) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setEditing(tx);
    }
  };

  return (
    <div className="tx-list">
      {groups.map((group, index) => (
        <Fragment key={group.day}>
          {(index === 0 || group.day.slice(0, 7) !== groups[index - 1].day.slice(0, 7)) && (
            <h3 className="tx-month">{monthLabel(group.day.slice(0, 7))}</h3>
          )}
        <section className="tx-day">
          <DayBadge day={group.day} />
          <h3 className="tx-day-head">
            <span>{dayHeading(group.day)}</span>
            {group.items.length > 1 && (
              <span className="num">{group.net >= 0 ? "+" : "−"}{money(Math.abs(group.net))}</span>
            )}
          </h3>
          <ul>
            {group.items.map((tx) => (
              <li
                key={tx.id}
                tabIndex={0}
                role="button"
                aria-label={`Edit ${tx.description}, ${moneyIn(tx.paid_cents, tx.currency)}`}
                onClick={() => setEditing(tx)}
                onKeyDown={(e) => onKey(e, tx)}
              >
                <CategoryIcon category={tx.category} hint={tx.description} />
                <div className="tx-main">
                  <span className="tx-name">
                    {tx.description}
                    {tx.recurring_id !== null && (
                      <span className="recurring-mark" title="Added automatically by a recurring rule"> ↻</span>
                    )}
                  </span>
                  <span className="tx-sub">{tx.category}</span>
                </div>
                <span className={`tx-amount num ${tx.kind === "income" ? "amount-income" : ""}`}>
                  {tx.kind === "income" ? "+" : "−"}{moneyIn(tx.paid_cents, tx.currency)}
                  {tx.currency !== displayCurrency() && <span className="tx-converted">{money(tx.amount_cents)}</span>}
                </span>
                <span className="row-chevron" aria-hidden="true">›</span>
              </li>
            ))}
          </ul>
        </section>
        </Fragment>
      ))}
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

function dayHeading(iso: string): string {
  const today = todayIso();
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  const pad = (n: number) => String(n).padStart(2, "0");
  if (iso === today) return "Today";
  if (iso === `${yesterday.getFullYear()}-${pad(yesterday.getMonth() + 1)}-${pad(yesterday.getDate())}`) return "Yesterday";
  // Other days: the date badge beside it already says which day.
  void date;
  return "";
}

/** Google Calendar's date badge: weekday over the day number, filled in for today. */
function DayBadge({ day }: { day: string }) {
  const [y, m, d] = day.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  const today = day === todayIso();
  return (
    <div className={`day-badge ${today ? "today" : ""}`} aria-hidden="true">
      <span className="dow">{date.toLocaleDateString("en-US", { weekday: "short" })}</span>
      <span className="dom">{d}</span>
    </div>
  );
}

export function EditTransactionSheet({ tx, onClose, onSaved }: { tx: Transaction; onClose: () => void; onSaved: () => void }) {
  const [kind, setKind] = useState<Kind>(tx.kind);
  const [description, setDescription] = useState(tx.description);
  // Edited in the currency it was paid in (NT$ for an NT$ account).
  const [amount, setAmount] = useState((tx.paid_cents / 100).toFixed(2));
  const [category, setCategory] = useState(tx.category);
  const [date, setDate] = useState(tx.occurred_on);
  const [account, setAccount] = useState<number | null>(tx.account_id);
  const accounts = useCashAccounts();
  const currency = accounts.find((a) => a.id === account)?.currency ?? (account === null ? "USD" : tx.currency);
  const [applyToMatching, setApplyToMatching] = useState(true);
  const [repeat, setRepeat] = useState<Frequency | "">("");
  const [fillMissing, setFillMissing] = useState(false);
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
        kind, description, amount, category, occurred_on: date, account_id: account,
        apply_category_to_matching: categoryChanged && matching > 0 && applyToMatching,
      });
      if (repeat) await api.makeRecurring(tx.id, repeat, fillMissing);
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
      <div className="sheet-hero">
        <CategoryIcon category={category || tx.category} hint={description} size={52} />
        <strong className={kind === "income" ? "amount-income" : ""}>
          {kind === "income" ? "+" : "−"}{currencySymbol(currency)}{amount || "0.00"}
        </strong>
      </div>
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
              <i>{currencySymbol(currency)}</i>
              <input type="text" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} required />
            </div>
          </label>
          <label className="field">
            <span>Date</span>
            <DateInput value={date} onChange={setDate} required />
          </label>
        </div>
        <label className="field">
          <span>Category</span>
          <input type="text" list="edit-categories" value={category} onChange={(e) => setCategory(e.target.value)} required />
          <datalist id="edit-categories">
            {categories.data?.map((c) => <option key={c} value={c} />)}
          </datalist>
        </label>
        <AccountField kind={kind} accounts={accounts} value={account} onChange={setAccount} />
        {categoryChanged && matching > 0 && (
          <label className="check-row">
            <input type="checkbox" checked={applyToMatching} onChange={(e) => setApplyToMatching(e.target.checked)} />
            Also move {matching} other “{tx.description}” transaction{matching === 1 ? "" : "s"} to this category
          </label>
        )}
        {tx.recurring_id !== null ? (
          <p className="hint" style={{ margin: 0 }}>
            ↻ Part of a recurring rule. Changes here apply to this one only; edit the rule on the Transactions page.
          </p>
        ) : (
          <div className="field">
            <span id="repeats-label">Repeats</span>
            <select aria-labelledby="repeats-label" value={repeat} onChange={(e) => setRepeat(e.target.value as Frequency | "")}>
              <option value="">Doesn't repeat</option>
              {FREQUENCIES.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
            </select>
            {repeat && (
              <>
                <span className="hint">
                  Future “{description || tx.description}” charges will be added automatically {frequencyText(repeat)},
                  starting from this one. Ones you already have (within a few days of each date) are linked, not
                  duplicated.
                </span>
                <label className="check-row">
                  <input type="checkbox" checked={fillMissing} onChange={(e) => setFillMissing(e.target.checked)} />
                  Also add any missing charges between {dateLabel(date)} and today
                </label>
              </>
            )}
          </div>
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
