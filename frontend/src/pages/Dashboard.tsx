import { useState, type CSSProperties } from "react";
import { api, type CategoryReport, type Pace } from "../api";
import { AiReview } from "../components/AiReview";
import {
  Allocation,
  CategoryBars,
  CategoryDonut,
  MonthlyChart,
  NetWorthChart,
  PaceChart,
  PurchaseBars,
  PurchaseDonut,
} from "../components/charts";
import { CapsCard } from "../components/CapsCard";
import { analyze, FocusReview, listNames } from "../components/FocusReview";
import { isOnline } from "../components/AiParts";
import { TransactionList } from "../components/TransactionList";
import { Upcoming } from "../components/Upcoming";
import { currentMonth, dateLabel, money, monthLabel, percent, signedMoney } from "../format";
import { useAsync } from "../hooks";
import { categoryColor } from "../icons";

/**
 * Home screen, laid out like Rocket Money: this month's spending and how it's
 * pacing against last month first, then net worth and upcoming bills, the AI
 * analyst, where the money went (narrowed to ticked categories if you like,
 * down to one category's purchases, with the AI on just those), and recent
 * transactions.
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
  // Checked once and shared by both AI panels (each check can take ~3 s when the PC is off).
  const ai = useAsync(api.aiStatus, []);

  const [chart, setChart] = useState<"pie" | "bars">(() => remembered("category-chart", "pie") as "pie" | "bars");
  const [hideCovered, setHideCovered] = useState(() => remembered("hide-covered", "no") === "yes");
  const covered = settings.data?.covered_categories ?? [];

  // Ticked categories. "all" (the default) is stored as such rather than as a
  // list, so a category you add later is ticked too. Lists are kept in
  // all-time order (biggest first) so nothing jumps around between months,
  // and names that no longer exist are dropped.
  const [picks, setPicks] = useState<Picks>(rememberedPicks);
  const allCategories = allTime.data?.items.map((i) => i.category);
  const chosen =
    picks === "all" ? (allCategories ?? [])
    : allCategories ? allCategories.filter((c) => picks.some((p) => p.toLowerCase() === c.toLowerCase()))
    : picks;
  const everything = picks === "all" || (!!allCategories?.length && chosen.length === allCategories.length);
  const choose = (next: string[]) => {
    const value: Picks = allCategories?.length && next.length >= allCategories.length ? "all" : next;
    setPicks(value);
    remember("category-picks", JSON.stringify(value));
  };
  const toggleCategory = (name: string) =>
    choose(chosen.includes(name) ? chosen.filter((c) => c !== name) : [...chosen, name]);
  // "All" ticks every box, or unticks them all if they're already all ticked.
  const toggleAll = () => choose(everything ? [] : (allCategories ?? []));
  // What the chart shows: everything, a few categories, one category's purchases, or nothing.
  const view = everything ? "all" : chosen.length === 0 ? "none" : chosen.length === 1 ? "one" : "some";
  const single = view === "one" ? chosen[0] : null;
  const purchases = useAsync(
    () => (single ? api.purchases(single, month) : Promise.resolve(null)),
    [single, month, version],
  );
  // The running-total line chart, for just the ticked categories.
  const narrowed = view === "some" || view === "one";
  const focusPace = useAsync(
    () => (narrowed ? api.pace(month, chosen) : Promise.resolve(null)),
    [narrowed ? chosen.join("\n") : null, month, version],
  );

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
                  {worth.data.worth.lines.some((l) => l.asset_type === "cash") && (
                    <div className="delta" title="Every cash account together: what you could spend right now">
                      Liquid <strong className="num">{money(worth.data.worth.liquid_cents)}</strong>
                    </div>
                  )}
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
        <AiReview month={month} version={version} status={ai} />
      </section>

      <CapsCard
        month={month}
        version={version}
        categories={allCategories ?? []}
        onChanged={onChanged}
        onWhy={(category) => {
          // Tick just that category, run the AI on it, and show it.
          choose([category]);
          if (isOnline(ai.data)) analyze(month, [category]);
          document.getElementById("spending-by-category")?.scrollIntoView({ behavior: "smooth", block: "start" });
        }}
      />

      <section id="spending-by-category" className={`card ${categories.loading && categories.data ? "refreshing" : ""}`} style={{ marginTop: 16 }}>
        <div className="card-head">
          <h2 className="card-title">Spending by category</h2>
          <span className="card-subtitle">
            {everything ? "All categories" : view === "none" ? "None ticked" : `${chosen.length} of ${allCategories?.length ?? "…"} categories`}
          </span>
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
        {allCategories && allCategories.length > 1 && (
          <div className="focus-picker">
            <div className="toggle-list" role="group" aria-label="Categories to show">
              <label className={`toggle ${everything ? "on" : chosen.length ? "mixed" : ""}`}>
                <input
                  type="checkbox"
                  checked={everything}
                  ref={(box) => {
                    if (box) box.indeterminate = !everything && chosen.length > 0;
                  }}
                  onChange={toggleAll}
                />
                All
              </label>
              {allCategories.map((name) => (
                <label key={name} className={`toggle ${chosen.includes(name) ? "on" : ""}`}
                  style={{ "--chip": categoryColor(name) } as CSSProperties}>
                  <input type="checkbox" checked={chosen.includes(name)} onChange={() => toggleCategory(name)} />
                  {name}
                </label>
              ))}
            </div>
          </div>
        )}
        <div className="category-layout">
          <div>
            {(view === "some" || view === "one") && categories.data && (
              <FocusTotal
                report={categories.data}
                focus={chosen}
                month={month}
                purchases={single && purchases.data?.category === single ? purchases.data.count : undefined}
              />
            )}
            {view === "all" && covered.length > 0 && (
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
            {categories.data && view === "none" && (
              <p className="chart-note">Nothing ticked. Tick some categories above, or press All.</p>
            )}
            {view === "one" && single && (
              purchases.error ? <p className="message error">{purchases.error}</p>
              : purchases.data?.category !== single ? <p className="chart-note">…</p>
              : chart === "pie" ? <PurchaseDonut report={purchases.data} />
              : <PurchaseBars report={purchases.data} />
            )}
            {categories.data && (view === "all" || view === "some") && (chart === "pie" ? (
              <CategoryDonut
                report={categories.data}
                colorOrder={allCategories ?? []}
                covered={covered}
                coveredLabel="Covered"
                hideCovered={hideCovered}
                focus={view === "some" ? chosen : []}
                onSelect={choose}
              />
            ) : (
              <CategoryBars
                report={
                  view === "some" ? onlyThese(categories.data, chosen)
                  : hideCovered ? withoutCovered(categories.data, covered)
                  : categories.data
                }
                emptyNote={view === "some" ? "No spending in these categories this month." : undefined}
                onSelect={choose}
              />
            ))}
            {narrowed && focusPace.data?.categories && <FocusPace pace={focusPace.data} />}
          </div>
          <FocusReview month={month} categories={chosen} everything={everything} status={ai} version={version} />
        </div>
      </section>

      <section className={`card ${monthly.loading && monthly.data ? "refreshing" : ""}`} style={{ marginTop: 16 }}>
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

/** "▲ $77.77 more than this point in October" (or the finished-month version). */
function PaceComparison({ pace }: { pace: Pace }) {
  const last = monthLabel(pace.previous_month).split(" ")[0];
  const diff = pace.difference_cents;
  if (!pace.through_day) return <span className="subtle">This month hasn't started yet.</span>;
  if (!pace.last_month_total_cents) return <span className="subtle">Nothing recorded in {last} to compare with.</span>;
  if (pace.in_progress) {
    return (
      <span className={diff > 0 ? "delta-bad" : "delta-good"}>
        {diff > 0 ? "▲" : "▼"} {money(Math.abs(diff))} {diff > 0 ? "more" : "less"} than this point in {last}
      </span>
    );
  }
  const full = pace.spent_cents - pace.last_month_total_cents;
  return (
    <span className={full > 0 ? "delta-bad" : "delta-good"}>
      {full > 0 ? "▲" : "▼"} {money(Math.abs(full))} {full > 0 ? "more" : "less"} than {last}
    </span>
  );
}

/** "Spent in November" with how it's pacing against the same days last month. */
function SpendHero({ pace }: { pace: Pace }) {
  const label = pace.controlled ? "Spending you control" : "Spent";
  return (
    <div className="spend-hero">
      <div className="eyebrow">
        {label} · {monthLabel(pace.month)}
        {pace.controlled && (
          <span className="subtle" title={`Leaves out ${pace.covered_categories.join(", ")}`}> (covered costs left out)</span>
        )}
      </div>
      <div className="hero">{money(pace.spent_cents)}</div>
      <div className="delta"><PaceComparison pace={pace} /></div>
      <PaceChart pace={pace} />
    </div>
  );
}

/** The same running-total chart as the top of the page, for the ticked categories only. */
function FocusPace({ pace }: { pace: Pace }) {
  return (
    <div className="focus-pace">
      <div className="eyebrow">Running total of these categories</div>
      <div className="delta"><PaceComparison pace={pace} /></div>
      <PaceChart pace={pace} />
    </div>
  );
}

/** "$70.00 on Food and Transport in November 2026, 17% of everything you spent." */
function FocusTotal({
  report,
  focus,
  month,
  purchases,
}: {
  report: CategoryReport;
  focus: string[];
  month: string;
  purchases?: number; // shown for a single category ("across 12 purchases")
}) {
  const total = onlyThese(report, focus).total_cents;
  const names = focus.length > 3 ? `these ${focus.length} categories` : listNames(focus);
  return (
    <p className="focus-total">
      <strong>{money(total)}</strong> on {names} in {monthLabel(month)}
      {purchases !== undefined && ` across ${purchases} purchase${purchases === 1 ? "" : "s"}`}
      {report.total_cents > 0 && `, ${percent(total / report.total_cents)} of everything you spent`}.
    </p>
  );
}

/** Just the chosen categories (including ones with $0 this month), shares out of their total. */
function onlyThese(report: CategoryReport, focus: string[]): CategoryReport {
  const byName = new Map(report.items.map((i) => [i.category.toLowerCase(), i.total_cents]));
  const rows = focus
    .map((category) => ({ category, total_cents: byName.get(category.toLowerCase()) ?? 0 }))
    .sort((a, b) => b.total_cents - a.total_cents); // stable: ties keep all-time order
  const total = rows.reduce((sum, r) => sum + r.total_cents, 0);
  return { ...report, total_cents: total, items: rows.map((r) => ({ ...r, share: total ? r.total_cents / total : 0 })) };
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
type Picks = "all" | string[];

function rememberedPicks(): Picks {
  try {
    const saved = JSON.parse(remembered("category-picks", "null"));
    if (saved === "all") return "all";
    if (Array.isArray(saved)) return saved.filter((v): v is string => typeof v === "string");
    // Before "All" ticked every box, an empty list meant "everything".
    const older = JSON.parse(remembered("category-focus", "[]"));
    return Array.isArray(older) && older.length ? older.filter((v): v is string => typeof v === "string") : "all";
  } catch {
    return "all";
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
