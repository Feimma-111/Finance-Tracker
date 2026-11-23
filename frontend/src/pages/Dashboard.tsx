import { useState } from "react";
import { api, type CategoryReport, type Pace } from "../api";
import { AiReview } from "../components/AiReview";
import { Allocation, CategoryBars, CategoryDonut, MonthlyChart, NetWorthChart, PaceChart } from "../components/charts";
import { TransactionList } from "../components/TransactionList";
import { Upcoming } from "../components/Upcoming";
import { currentMonth, dateLabel, money, monthLabel, signedMoney } from "../format";
import { useAsync } from "../hooks";

/**
 * Home screen, laid out like Rocket Money: this month's spending and how it's
 * pacing against last month first, then net worth and upcoming bills, the AI
 * analyst, where the money went, and recent transactions.
 */
export function Dashboard({ version, onChanged }: { version: number; onChanged: () => void }) {
  const [month, setMonth] = useState(currentMonth());

  const worth = useAsync(async () => ({ worth: await api.netWorth(), history: await api.netWorthHistory() }), [version]);
  const months = useAsync(api.months, [version]);
  const summary = useAsync(() => api.summary(month), [month, version]);
  const pace = useAsync(() => api.pace(month), [month, version]);
  const categories = useAsync(() => api.categoryReport(month), [month, version]);
  const monthly = useAsync(api.monthlyReport, [version]);
  const recent = useAsync(() => api.transactions(), [version]);
  // For the donut: all-time ranking (which category owns which color) and covered expenses.
  const allTime = useAsync(() => api.categoryReport(null), [version]);
  const settings = useAsync(api.settings, [version]);

  const [chart, setChart] = useState<"pie" | "bars">(() => remembered("category-chart", "pie") as "pie" | "bars");
  const [hideCovered, setHideCovered] = useState(() => remembered("hide-covered", "no") === "yes");
  const covered = settings.data?.covered_categories ?? [];

  const monthOptions = months.data ?? [month];

  return (
    <>
      {/* One filter row; everything on the page except net worth follows the chosen month. */}
      <div className="filter-row page-filter">
        <select id="month-filter" aria-label="Month" value={month} onChange={(e) => setMonth(e.target.value)} className="month-select">
          {monthOptions.map((m) => (
            <option key={m} value={m}>{monthLabel(m)}</option>
          ))}
        </select>
        {month !== currentMonth() && (
          <button className="btn-link" onClick={() => setMonth(currentMonth())}>Back to this month</button>
        )}
      </div>

      <section className="grid grid-3">
        <div className={`card span-2 ${pace.loading && pace.data ? "refreshing" : ""}`}>
          {pace.error && <p className="message error">{pace.error}</p>}
          {pace.data ? <SpendHero pace={pace.data} /> : !pace.error && <div className="hero subtle">…</div>}
        </div>
        <div className={`stack stat-stack ${summary.loading && summary.data ? "refreshing" : ""}`}>
          <StatTile label="Income" value={summary.data?.income_cents} />
          <StatTile
            label="Net"
            value={summary.data?.net_cents}
            note={summary.data ? (summary.data.net_cents >= 0 ? "You saved money" : "You spent more than you earned") : undefined}
          />
          <StatTile label="Total spent" value={summary.data?.spent_cents} note={covered.length ? "Including covered costs" : undefined} />
        </div>
      </section>

      <section className="grid grid-3" style={{ marginTop: 16 }}>
        <div className={`card span-2 ${worth.loading && worth.data ? "refreshing" : ""}`}>
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
                    <div style={{ marginTop: 16 }}>
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
            <div>{worth.data && <NetWorthChart history={worth.data.history} />}</div>
          </div>
        </div>
        <div className="card">
          <div className="card-head">
            <h2 className="card-title">Upcoming</h2>
            <span className="card-subtitle">Next 30 days</span>
            <a className="card-action" href="#/transactions">Manage</a>
          </div>
          <Upcoming version={version} />
        </div>
      </section>

      <section style={{ marginTop: 16 }}>
        <AiReview month={month} version={version} />
      </section>

      <section className="grid grid-2" style={{ marginTop: 16 }}>
        <div className={`card ${categories.loading && categories.data ? "refreshing" : ""}`}>
          <div className="card-head">
            <h2 className="card-title">Spending by category</h2>
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
              Hide covered expenses ({covered.join(", ")})
            </label>
          )}
          {categories.error && <p className="message error">{categories.error}</p>}
          {categories.data && (chart === "pie" ? (
            <CategoryDonut
              report={categories.data}
              colorOrder={allTime.data?.items.map((i) => i.category) ?? []}
              covered={covered}
              coveredLabel="Covered"
              hideCovered={hideCovered}
            />
          ) : (
            <CategoryBars report={hideCovered ? withoutCovered(categories.data, covered) : categories.data} />
          ))}
        </div>
        <div className={`card ${monthly.loading && monthly.data ? "refreshing" : ""}`}>
          <div className="card-head">
            <h2 className="card-title">Monthly spending</h2>
            <span className="card-subtitle">Click a month to see it</span>
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

      <section className="card" style={{ marginTop: 16 }}>
        <div className="card-head">
          <h2 className="card-title">Recent transactions</h2>
          <a className="card-action" href="#/transactions">See all</a>
        </div>
        {recent.data && <TransactionList items={recent.data.items.slice(0, 8)} onChanged={onChanged} />}
      </section>
    </>
  );
}

/** "Spent in November" with how it's pacing against the same days last month. */
function SpendHero({ pace }: { pace: Pace }) {
  const label = pace.controlled ? "Spending you control" : "Spent";
  const last = monthLabel(pace.previous_month).split(" ")[0];
  const diff = pace.difference_cents;
  let comparison;
  if (!pace.through_day) {
    comparison = <span className="subtle">This month hasn't started yet.</span>;
  } else if (!pace.last_month_total_cents) {
    comparison = <span className="subtle">Nothing recorded in {last} to compare with.</span>;
  } else if (pace.in_progress) {
    comparison = (
      <span className={diff > 0 ? "delta-bad" : "delta-good"}>
        {diff > 0 ? "▲" : "▼"} {money(Math.abs(diff))} {diff > 0 ? "more" : "less"} than this point in {last}
      </span>
    );
  } else {
    const full = pace.spent_cents - pace.last_month_total_cents;
    comparison = (
      <span className={full > 0 ? "delta-bad" : "delta-good"}>
        {full > 0 ? "▲" : "▼"} {money(Math.abs(full))} {full > 0 ? "more" : "less"} than {last}
      </span>
    );
  }
  return (
    <div className="spend-hero">
      <div className="eyebrow">
        {label} · {monthLabel(pace.month)}
        {pace.controlled && (
          <span className="subtle" title={`Leaves out ${pace.covered_categories.join(", ")}`}> (covered costs left out)</span>
        )}
      </div>
      <div className="hero">{money(pace.spent_cents)}</div>
      <div className="delta">{comparison}</div>
      <PaceChart pace={pace} />
    </div>
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
    <div className="card stat-tile">
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
