import { useState } from "react";
import { api, CSV_EXPORT_URL } from "../api";
import { TransactionForm } from "../components/forms";
import { TransactionTable } from "../components/TransactionTable";
import { money, monthLabel } from "../format";
import { useAsync } from "../hooks";

export function Transactions({ version, onChanged }: { version: number; onChanged: () => void }) {
  const [month, setMonth] = useState<string>(""); // "" = all time
  const months = useAsync(api.months, [version]);
  const list = useAsync(() => api.transactions(month || null), [month, version]);

  const items = list.data?.items ?? [];
  const spent = items.filter((t) => t.kind === "expense").reduce((s, t) => s + t.amount_cents, 0);
  const income = items.filter((t) => t.kind === "income").reduce((s, t) => s + t.amount_cents, 0);

  return (
    <>
      <h1 className="page-title">Transactions</h1>
      <div className="filter-row" style={{ marginTop: 0 }}>
        <label htmlFor="tx-month">Showing</label>
        <select id="tx-month" value={month} onChange={(e) => setMonth(e.target.value)}>
          <option value="">All time</option>
          {months.data?.map((m) => <option key={m} value={m}>{monthLabel(m)}</option>)}
        </select>
        {list.data && (
          <span className="subtle">
            {items.length} transactions · spent {money(spent)} · income {money(income)}
          </span>
        )}
        <span className="spacer" />
        <a className="btn btn-small" href={CSV_EXPORT_URL} download>Export CSV</a>
      </div>

      <div className="grid grid-3">
        <div className={`card span-2 ${list.loading && list.data ? "refreshing" : ""}`}>
          {list.error && <p className="message error">{list.error}</p>}
          {list.data && <TransactionTable items={items} onChanged={onChanged} />}
        </div>
        <div className="card" style={{ alignSelf: "start" }}>
          <div className="card-head">
            <h2 className="card-title">Add a transaction</h2>
          </div>
          <TransactionForm onSaved={onChanged} version={version} />
        </div>
      </div>
    </>
  );
}
