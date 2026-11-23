import { useState } from "react";
import { api, CSV_EXPORT_URL } from "../api";
import { RecurringList } from "../components/RecurringList";
import { TransactionList } from "../components/TransactionList";
import { money, monthLabel } from "../format";
import { useAsync } from "../hooks";
import { TabIcons } from "../icons";

export function Transactions({ version, onChanged }: { version: number; onChanged: () => void }) {
  const [month, setMonth] = useState<string>(""); // "" = all time
  const [search, setSearch] = useState("");
  const months = useAsync(api.months, [version]);
  const list = useAsync(() => api.transactions(month || null), [month, version]);

  // Search matches the description, category, or amount ("coffee", "rent", "4.50").
  const needle = search.trim().toLowerCase();
  const items = (list.data?.items ?? []).filter(
    (t) =>
      !needle ||
      t.description.toLowerCase().includes(needle) ||
      t.category.toLowerCase().includes(needle) ||
      (t.amount_cents / 100).toFixed(2).includes(needle.replace(/[$,]/g, "")),
  );
  const spent = items.filter((t) => t.kind === "expense").reduce((s, t) => s + t.amount_cents, 0);
  const income = items.filter((t) => t.kind === "income").reduce((s, t) => s + t.amount_cents, 0);

  return (
    <>
      <h1 className="page-title">Transactions</h1>
      <div className="grid grid-3">
        <div className="stack span-2" style={{ alignContent: "start" }}>
          <div className="toolbar">
            <label className="search-field">
              {TabIcons.search}
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search transactions"
                aria-label="Search transactions"
              />
            </label>
            <select aria-label="Month" value={month} onChange={(e) => setMonth(e.target.value)}>
              <option value="">All time</option>
              {months.data?.map((m) => <option key={m} value={m}>{monthLabel(m)}</option>)}
            </select>
          </div>
          {list.data && (
            <div className="summary-strip">
              <span><strong className="num">{items.length}</strong> transactions</span>
              <span>Spent <strong className="num">{money(spent)}</strong></span>
              <span>Income <strong className="num amount-income">{money(income)}</strong></span>
              <a className="btn btn-small" href={CSV_EXPORT_URL} download>Export CSV</a>
            </div>
          )}
          <div className={`card ${list.loading && list.data ? "refreshing" : ""}`}>
            {list.error && <p className="message error">{list.error}</p>}
            {list.data && (
              <TransactionList
                items={items}
                onChanged={onChanged}
                emptyText={needle ? `Nothing matches “${search.trim()}”.` : "No transactions yet. Tap + Add to record one."}
              />
            )}
          </div>
        </div>
        <div className="card" style={{ alignSelf: "start" }}>
          <div className="card-head">
            <h2 className="card-title">Recurring</h2>
            <span className="card-subtitle">Added automatically when due</span>
          </div>
          <RecurringList version={version} onChanged={onChanged} />
        </div>
      </div>
    </>
  );
}
