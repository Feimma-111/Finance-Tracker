import { useState } from "react";
import { api, type CategoryReport } from "../api";
import { AiReview } from "../components/AiReview";
import { Allocation, CategoryBars, CategoryDonut, MonthlyChart, NetWorthChart } from "../components/charts";
import { TransactionForm } from "../components/forms";
import { TransactionTable } from "../components/TransactionTable";
import { currentMonth, dateLabel, money, monthLabel, signedMoney } from "../format";
import { useAsync } from "../hooks";

export function Dashboard({ version, onChanged }: { version: number; onChanged: () => void }) {
  const [month, setMonth] = useState(currentMonth());

  const worth = useAsync(async () => ({ worth: await api.netWorth(), history: await api.netWorthHistory() }), [version]);
  const months = useAsync(api.months, [version]);
  const summary = useAsync(() => api.summary(month), [month, version]);
  const categories = useAsync(() => api.categoryReport(month), [month, version]);
  const monthly = useAsync(api.monthlyReport, [version]);
  const recent = useAsync(() => api.transactions(), [version]);
  // For the donut: all-time ranking (which category owns which color) and covered expenses.
  const allTime = useAsync(() => api.categoryReport(null), [version]);
  const settings = useAsync(api.settings, [version]);

  const [chart, setChart] = useState<"pie" | "bars">(() => remembered("category-chart", "pie") as "pie" | "bars");
  const [hideCovered, setHideCovered] = useState(() => remembered("hide-covered", "no") === "yes");
  const covered = settings.data?.covered_categories ?? [];
  const coveredLabel = "Covered";

  const monthOptions = months.data ?? [month];

  return (
    <>
      {/* Net worth isn't tied to a month, so it sits above the month filter. */}
      <section className={`card ${worth.loading && worth.data ? "refreshing" : ""}`}>
        <div className="networth-layout">
          <div>
            <div className="eyebrow">Net worth</div>
            {worth.error && <p className="message error">{worth.error}</p>}
            {worth.data && (
              <>
                <div className="hero">{money(worth.data.worth.total_cents)}</div>
                <NetWorthDelta change={worth.data.worth.change_cents} since={worth.data.worth.change_since} />
                {!worth.data.worth.complete && (
                  <p className="message error">Some holdings couldn't be priced, so this total is incomplete.</p>
                )}
                {worth.data.worth.lines.length ? (
                  <div style={{ marginTop: 18 }}>
                    <Allocation worth={worth.data.worth} />
                  </div>
                ) : (
                  <p className="hint">
                    Add your cash, stocks, crypto, or gold on the <a href="#/holdings">Holdings</a> page to track this.
                  </p>
                )}
              </>
            )}
            {!worth.data && !worth.error && <div className="hero subtle">…</div>}
          </div>
          <div>
            <div className="eyebrow" style={{ marginBottom: 8 }}>Over time</div>
            {worth.data && <NetWorthChart history={worth.data.history} />}
          </div>
        </div>
      </section>

      {/* One filter row; everything below it follows the chosen month. */}
      <div className="filter-row">
        <label htmlFor="month-filter">Showing</label>
        <select id="month-filter" value={month} onChange={(e) => setMonth(e.target.value)}>
          {monthOptions.map((m) => (
            <option key={m} value={m}>{monthLabel(m)}</option>
          ))}
        </select>
        {month !== currentMonth() && (
          <button className="btn-link" onClick={() => setMonth(currentMonth())}>Back to this month</button>
        )}
      </div>

      <section className={`grid grid-3 ${summary.loading && summary.data ? "refreshing" : ""}`}>
        <StatTile label="Spent" value={summary.data?.spent_cents} />
        <StatTile label="Income" value={summary.data?.income_cents} />
        <StatTile
          label="Net"
          value={summary.data?.net_cents}
          note={summary.data ? (summary.data.net_cents >= 0 ? "You saved money" : "You spent more than you earned") : undefined}
        />
      </section>

      <section style={{ marginTop: 16 }}>
        <AiReview month={month} version={version} />
      </section>

      <section className="grid grid-2" style={{ marginTop: 16 }}>
        <div className={`card ${categories.loading && categories.data ? "refreshing" : ""}`}>
          <div className="card-head">
            <h2 className="card-title">Spending by category</h2>
            <span className="card-subtitle">{monthLabel(month)}</span>
            <div className="card-action">
              <div className="segmented" role="group" aria-label="Chart type">
                {(["pie", "bars"] as const).map((kind) => (
                  <button
                    key={kind}
                    type="button"
                    aria-pressed={chart === kind}
                    onClick={() => {
                      setChart(kind);
                      remember("category-chart", kind);
                    }}
                  >
                    {kind === "pie" ? "Pie" : "Bars"}
                  </button>
                ))}
              </div>
            </div>
          </div>
          {covered.length > 0 && (
            <label className="check-row" style={{ marginBottom: 12 }}>
              <input
                type="checkbox"
                checked={hideCovered}
                onChange={(e) => {
                  setHideCovered(e.target.checked);
                  remember("hide-covered", e.target.checked ? "yes" : "no");
                }}
              />
              Hide covered expenses ({covered.join(", ")}{settings.data?.covered_note ? ` · ${settings.data.covered_note}` : ""})
            </label>
          )}
          {categories.error && <p className="message error">{categories.error}</p>}
          {categories.data && (chart === "pie" ? (
            <CategoryDonut
              report={categories.data}
              colorOrder={allTime.data?.items.map((i) => i.category) ?? []}
              covered={covered}
              coveredLabel={coveredLabel}
              hideCovered={hideCovered}
            />
          ) : (
            <CategoryBars report={hideCovered ? withoutCovered(categories.data, covered) : categories.data} />
          ))}
        </div>
        <div className={`card ${monthly.loading && monthly.data ? "refreshing" : ""}`}>
          <div className="card-head">
            <h2 className="card-title">Monthly spending</h2>
            <span className="card-subtitle">Click a month to see its categories</span>
          </div>
          {monthly.error && <p className="message error">{monthly.error}</p>}
          {monthly.data && (
            <MonthlyChart
              months={monthly.data.months}
              meanCents={monthly.data.mean_cents}
              selected={month}
              onSelect={setMonth}
            />
          )}
        </div>
      </section>

      <section className="grid grid-2" style={{ marginTop: 16 }}>
        <div className="card">
          <div className="card-head">
            <h2 className="card-title">Add a transaction</h2>
          </div>
          <TransactionForm onSaved={onChanged} version={version} />
        </div>
        <div className="card">
          <div className="card-head">
            <h2 className="card-title">Recent transactions</h2>
            <a className="card-action" href="#/transactions">See all</a>
          </div>
          {recent.data && <TransactionTable items={recent.data.items.slice(0, 7)} onChanged={onChanged} />}
        </div>
      </section>
    </>
  );
}

/** The category report minus covered categories (shares recomputed for display). */
function withoutCovered(report: CategoryReport, covered: string[]): CategoryReport {
  const hidden = new Set(covered.map((c) => c.toLowerCase()));
  const items = report.items.filter((i) => !hidden.has(i.category.toLowerCase()));
  const total = items.reduce((sum, i) => sum + i.total_cents, 0);
  return { ...report, total_cents: total, items: items.map((i) => ({ ...i, share: total ? i.total_cents / total : 0 })) };
}

// Small per-device view preferences (chart type, hide covered). Not data, so
// localStorage is fine; any failure just means the default is used.
function remembered(key: string, fallback: string): string {
  try {
    return localStorage.getItem(`finance-tracker:${key}`) ?? fallback;
  } catch {
    return fallback;
  }
}
function remember(key: string, value: string): void {
  try {
    localStorage.setItem(`finance-tracker:${key}`, value);
  } catch {
    // ignore
  }
}

function StatTile({ label, value, note }: { label: string; value?: number; note?: string }) {
  return (
    <div className="card">
      <div className="eyebrow">{label}</div>
      <div className="tile-value">{value === undefined ? "…" : money(value)}</div>
      {note && <div className="tile-note">{note}</div>}
    </div>
  );
}

function NetWorthDelta({ change, since }: { change: number | null; since: string | null }) {
  if (change === null || since === null) return <div className="delta">First check-in recorded today</div>;
  const direction = change > 0 ? "up" : change < 0 ? "down" : "";
  const arrow = change > 0 ? "▲" : change < 0 ? "▼" : "";
  return (
    <div className={`delta ${direction}`}>
      {arrow} {signedMoney(change)} <span className="subtle">since {dateLabel(since)}</span>
    </div>
  );
}
