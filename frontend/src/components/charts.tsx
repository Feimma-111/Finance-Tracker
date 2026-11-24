import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Line,
  LineChart,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { KeyboardEvent } from "react";
import type { CategoryReport, MonthRow, NetWorth, Pace, PurchaseReport, Snapshot } from "../api";
import { CategoryIcon } from "../icons";
import { assetMeta, axisWidth, dateLabel, dateShort, money, moneyAxis, monthLabel, monthShort, percent, seriesVar } from "../format";
import { useChartTheme } from "../hooks";

const axisTick = (color: string) => ({ fill: color, fontSize: 12 });

/** Props that make a list row act like a button: click, or Enter / Space from the keyboard. */
function pressable(onPress?: () => void) {
  if (!onPress) return {};
  return {
    className: "pressable",
    role: "button" as const,
    tabIndex: 0,
    onClick: onPress,
    onKeyDown: (e: KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onPress();
      }
    },
  };
}

/** Picking categories from a chart: the names to tick (just one, or everything in "Other"). */
export type SelectCategories = (categories: string[]) => void;

/* ------------------------------------------------------------------ monthly spending
   One series, so every bar is the same blue; the month you're looking at is
   emphasized and the rest step back. Unusual months get a text flag above the
   bar -- the label carries the meaning, not color. */

const FLAGS: Record<string, string> = {
  "well above usual": "▲ high",
  "above usual": "▲ high",
  "below usual": "▼ low",
  "well below usual": "▼ low",
  "in progress": "so far",
};

export function MonthlyChart({
  months,
  meanCents,
  selected,
  onSelect,
}: {
  months: MonthRow[];
  meanCents: number | null;
  selected: string;
  onSelect: (month: string) => void;
}) {
  const t = useChartTheme();
  if (!months.length) return <p className="chart-note">No spending recorded yet.</p>;
  const data = months.map((m) => ({ ...m, flag: FLAGS[m.label] ?? "" }));

  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={data} margin={{ top: 22, right: 56, bottom: 0, left: 0 }} barCategoryGap="22%">
          <CartesianGrid vertical={false} stroke={t.grid} />
          <XAxis
            dataKey="month"
            tickFormatter={monthShort}
            tickLine={false}
            axisLine={{ stroke: t.axis }}
            tick={axisTick(t.muted)}
            interval="preserveStartEnd"
            minTickGap={2}
          />
          <YAxis tickFormatter={moneyAxis} tickLine={false} axisLine={false} tick={axisTick(t.muted)} width={axisWidth()} />
          <Tooltip
            cursor={{ fill: t.hover }}
            content={({ active, payload }) => {
              const row = active && payload?.[0]?.payload as (MonthRow & { flag: string }) | undefined;
              if (!row) return null;
              return (
                <div className="chart-tooltip">
                  <strong>{monthLabel(row.month)}</strong>
                  {money(row.total_cents)}
                  {row.label && <span className="subtle">{row.label}</span>}
                  <span className="subtle">Click to see categories</span>
                </div>
              );
            }}
          />
          {meanCents !== null && (
            <ReferenceLine
              y={meanCents}
              stroke={t.ink2}
              strokeWidth={1}
              ifOverflow="extendDomain"
              label={{ value: `avg ${moneyAxis(meanCents)}`, position: "right", fill: t.ink2, fontSize: 11 }}
            />
          )}
          <Bar
            dataKey="total_cents"
            radius={[4, 4, 0, 0]}
            maxBarSize={40}
            isAnimationActive={false}
            cursor="pointer"
            onClick={(entry: { payload?: MonthRow }) => entry.payload && onSelect(entry.payload.month)}
          >
            {data.map((row) => (
              <Cell key={row.month} fill={row.month === selected ? t.series1 : t.series1Muted} />
            ))}
            <LabelList
              dataKey="flag"
              content={(props) => {
                // Drawn by hand: the default label wraps to the bar's width.
                const { x, y, width, value } = props as { x?: number; y?: number; width?: number; value?: string };
                if (!value || x === undefined || y === undefined) return null;
                return (
                  // The surface-colored stroke is a halo, so the average line
                  // never strikes through a label sitting at the same height.
                  <text
                    x={x + (width ?? 0) / 2}
                    y={y - 7}
                    textAnchor="middle"
                    fill={t.ink2}
                    fontSize={11}
                    stroke={t.surface}
                    strokeWidth={4}
                    paintOrder="stroke"
                  >
                    {value}
                  </text>
                );
              }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <TableView
        headers={["Month", "Spent", "Compared to usual"]}
        rows={months.map((m) => [monthLabel(m.month), money(m.total_cents), m.label || "typical"])}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ net worth over time */

export function NetWorthChart({ history }: { history: Snapshot[] }) {
  const t = useChartTheme();
  if (history.length < 2) {
    return (
      <p className="chart-note">
        Your net worth is recorded once a day when you open the app.
        <br />
        Come back tomorrow to start seeing a trend.
      </p>
    );
  }
  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={history} margin={{ top: 10, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke={t.grid} />
          <XAxis
            dataKey="date"
            tickFormatter={dateShort}
            tickLine={false}
            axisLine={{ stroke: t.axis }}
            tick={axisTick(t.muted)}
            minTickGap={40}
          />
          <YAxis
            domain={["auto", "auto"]}
            tickFormatter={moneyAxis}
            tickLine={false}
            axisLine={false}
            tick={axisTick(t.muted)}
            width={axisWidth()}
          />
          <Tooltip
            cursor={{ stroke: t.axis, strokeWidth: 1 }}
            content={({ active, payload }) => {
              const point = active && (payload?.[0]?.payload as Snapshot | undefined);
              if (!point) return null;
              return (
                <div className="chart-tooltip">
                  <strong>{dateLabel(point.date)}</strong>
                  {money(point.total_cents)}
                </div>
              );
            }}
          />
          <Line
            type="monotone"
            dataKey="total_cents"
            stroke={t.series1}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 5, stroke: t.surface, strokeWidth: 2, fill: t.series1 }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
      <TableView
        headers={["Date", "Net worth"]}
        rows={[...history].reverse().map((s) => [dateLabel(s.date), money(s.total_cents)])}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ spending pace (Rocket Money's "current spend")
   Running total through the month (blue) against the same days of last month
   (gray). Two series, so there's always a legend; the lines differ in color
   and in weight, so they don't rely on color alone. */

export function PaceChart({ pace }: { pace: Pace }) {
  const t = useChartTheme();
  const thisLabel = monthShort(pace.month);
  const lastLabel = monthShort(pace.previous_month);
  const days = Math.max(pace.days_in_month, pace.last_month.length);
  const data = Array.from({ length: days }, (_, i) => ({
    day: i + 1,
    current: pace.this_month[i]?.cumulative_cents,
    previous: pace.last_month[i]?.cumulative_cents,
  }));
  if (!pace.this_month.length && !pace.last_month.length) return <p className="chart-note">No spending yet.</p>;

  return (
    <div className="chart">
      <div className="series-legend" aria-hidden="true">
        <span><i style={{ background: t.series1 }} />{thisLabel}</span>
        <span><i style={{ background: t.muted }} />{lastLabel}</span>
      </div>
      <ResponsiveContainer width="100%" height={190}>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke={t.grid} />
          <XAxis
            dataKey="day"
            tickLine={false}
            axisLine={{ stroke: t.axis }}
            tick={axisTick(t.muted)}
            ticks={[1, 8, 15, 22, days]}
          />
          <YAxis tickFormatter={moneyAxis} tickLine={false} axisLine={false} tick={axisTick(t.muted)} width={axisWidth()} />
          <Tooltip
            cursor={{ stroke: t.axis, strokeWidth: 1 }}
            content={({ active, payload }) => {
              const p = active && (payload?.[0]?.payload as (typeof data)[number] | undefined);
              if (!p) return null;
              return (
                <div className="chart-tooltip">
                  <strong>Day {p.day}</strong>
                  {p.current !== undefined && <span className="subtle">{thisLabel}: {money(p.current)}</span>}
                  {p.previous !== undefined && <span className="subtle">{lastLabel}: {money(p.previous)}</span>}
                </div>
              );
            }}
          />
          <Line type="monotone" dataKey="previous" stroke={t.muted} strokeWidth={1.5} dot={false}
            isAnimationActive={false} connectNulls />
          <Line type="monotone" dataKey="current" stroke={t.series1} strokeWidth={2.5} isAnimationActive={false}
            activeDot={{ r: 5, stroke: t.surface, strokeWidth: 2, fill: t.series1 }}
            dot={(props: { cx?: number; cy?: number; index?: number }) =>
              props.index === pace.this_month.length - 1 && props.cx !== undefined && props.cy !== undefined ? (
                <circle key="end" cx={props.cx} cy={props.cy} r={4.5} fill={t.series1} stroke={t.surface} strokeWidth={2} />
              ) : (
                <g key={props.index} />
              )
            }
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ------------------------------------------------------------------ spending by category
   Ranked bars instead of a pie: lengths are much easier to compare than
   slice angles, and every bar carries its own value and share. */

const MAX_CATEGORY_ROWS = 8;

interface BarRow {
  key: string;
  label: string;
  note?: string; // e.g. "×3" after a purchase's name
  icon: { category: string; hint?: string };
  total_cents: number;
  share: number;
  select?: string[]; // categories to tick when the row is clicked
}

function RankBars({ rows, label, onSelect }: { rows: BarRow[]; label: string; onSelect?: SelectCategories }) {
  const largest = Math.max(...rows.map((r) => r.total_cents));
  return (
    <ol className="rank-bars" aria-label={label}>
      {rows.map((row) => {
        const select = onSelect && row.select?.length ? () => onSelect(row.select!) : undefined;
        return (
          <li
            key={row.key}
            title={`${row.label}: ${money(row.total_cents)} (${percent(row.share)})${select ? " · Click to see just this" : ""}`}
            {...pressable(select)}
          >
            <span className="label">
              <CategoryIcon category={row.icon.category} hint={row.icon.hint} size={28} />
              <span>
                {row.label}
                {row.note && <span className="subtle"> {row.note}</span>}
              </span>
            </span>
            <span className="track" aria-hidden="true">
              {/* The 3px minimum keeps tiny amounts visible; $0 gets no bar at all. */}
              <span
                className="fill"
                style={{ width: `${(row.total_cents / largest) * 100}%`, minWidth: row.total_cents > 0 ? undefined : 0 }}
              />
            </span>
            <span className="value">{money(row.total_cents)}</span>
            <span className="share">{percent(row.share)}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** Rows past the first seven become one "Other" row. */
function capRows(rows: BarRow[], total: number, otherSelect: (rest: BarRow[]) => string[] | undefined): BarRow[] {
  if (rows.length <= MAX_CATEGORY_ROWS) return rows;
  const rest = rows.slice(MAX_CATEGORY_ROWS - 1);
  const restTotal = rest.reduce((sum, r) => sum + r.total_cents, 0);
  return [
    ...rows.slice(0, MAX_CATEGORY_ROWS - 1),
    {
      key: "__other", label: `Other (${rest.length})`, icon: { category: "Other" },
      total_cents: restTotal, share: total ? restTotal / total : 0, select: otherSelect(rest),
    },
  ];
}

export function CategoryBars({
  report,
  emptyNote,
  onSelect,
}: {
  report: CategoryReport;
  emptyNote?: string;
  onSelect?: SelectCategories;
}) {
  if (!report.items.length || !report.total_cents) {
    return <p className="chart-note">{emptyNote ?? "No spending recorded for this period."}</p>;
  }
  const rows = report.items.map((i) => ({
    key: i.category, label: i.category, icon: { category: i.category },
    total_cents: i.total_cents, share: i.share, select: [i.category],
  }));
  const capped = capRows(rows, report.total_cents, (rest) => rest.map((r) => r.key));
  return <RankBars rows={capped} label="Spending by category" onSelect={onSelect} />;
}

/** One category broken down by purchase ("Boba ×3"). */
export function PurchaseBars({ report }: { report: PurchaseReport }) {
  if (!report.total_cents) return <p className="chart-note">No purchases in {report.category} this month.</p>;
  const rows = report.items.map((i) => ({
    key: i.description, label: i.description, note: i.count > 1 ? `×${i.count}` : undefined,
    icon: { category: i.description, hint: report.category }, total_cents: i.total_cents, share: i.share,
  }));
  return <RankBars rows={capRows(rows, report.total_cents, () => undefined)} label={`${report.category} by purchase`} />;
}

/* ------------------------------------------------------------------ allocation by asset type
   Part-to-whole in one segmented bar. Each asset type always has the same
   color, and the legend repeats every value as text. */

export function Allocation({ worth }: { worth: NetWorth }) {
  const total = worth.by_type.reduce((sum, t) => sum + Math.max(t.value_cents, 0), 0);
  if (!total) return null;
  return (
    <div className="allocation">
      <div className="allocation-bar" role="img" aria-label="Allocation by asset type">
        {worth.by_type
          .filter((t) => t.value_cents > 0)
          .map((t) => (
            <span
              key={t.asset_type}
              title={`${assetMeta(t.asset_type).label}: ${money(t.value_cents)} (${percent(t.value_cents / total)})`}
              style={{ flexGrow: t.value_cents, background: seriesVar(assetMeta(t.asset_type).slot) }}
            />
          ))}
      </div>
      <ul className="legend">
        {worth.by_type.map((t) => (
          <li key={t.asset_type}>
            <span className="swatch" style={{ background: seriesVar(assetMeta(t.asset_type).slot) }} />
            <span>{assetMeta(t.asset_type).label}</span>
            <span className="value">{money(t.value_cents)}</span>
            <span className="share">{percent(Math.max(t.value_cents, 0) / total)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ------------------------------------------------------------------ donut charts
   Slices keep a FIXED order (the order of their colors), not biggest-first:
   the colors were checked for colorblind safety as neighbors in that order,
   and a fixed order means a category never jumps around between months.
   A 2px gap in the card's color separates slices, and the legend beside the
   ring repeats every value as text. */

export interface Slice {
  key: string;
  label: string;
  value_cents: number;
  color: string; // a CSS color or var(--...)
  select?: string[]; // categories to tick when this slice (or its legend row) is clicked
}

export function Donut({
  slices,
  centerLabel,
  listEmpty = false,
  emptyNote = "Nothing to show for this period.",
  onSelect,
}: {
  slices: Slice[];
  centerLabel: string;
  listEmpty?: boolean; // keep $0 slices in the legend (chosen categories with nothing this month)
  emptyNote?: string;
  onSelect?: SelectCategories;
}) {
  const t = useChartTheme();
  const total = slices.reduce((sum, s) => sum + Math.max(s.value_cents, 0), 0);
  if (!total) return <p className="chart-note">{emptyNote}</p>;
  const visible = slices.filter((s) => s.value_cents > 0);
  const listed = listEmpty ? slices : visible;
  const pick = (s?: Slice) => (onSelect && s?.select?.length ? () => onSelect(s.select!) : undefined);

  return (
    <div className="donut-layout">
      <div className="donut" role="img" aria-label={`${centerLabel}: ${money(total)}`}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={visible}
              dataKey="value_cents"
              nameKey="label"
              innerRadius="64%"
              outerRadius="100%"
              startAngle={90}
              endAngle={-270}
              stroke={t.surface}
              strokeWidth={2}
              isAnimationActive={false}
              onClick={(_: unknown, index: number) => pick(visible[index])?.()}
            >
              {visible.map((s) => (
                <Cell key={s.key} fill={s.color} cursor={pick(s) ? "pointer" : undefined} />
              ))}
            </Pie>
            <Tooltip
              content={({ active, payload }) => {
                const s = active && (payload?.[0]?.payload as Slice | undefined);
                if (!s) return null;
                return (
                  <div className="chart-tooltip">
                    <strong>{s.label}</strong>
                    {money(s.value_cents)} · {percent(s.value_cents / total)}
                    {pick(s) && <span className="subtle">Click to see just {s.select!.length > 1 ? "these" : "this"}</span>}
                  </div>
                );
              }}
            />
          </PieChart>
        </ResponsiveContainer>
        <div className="donut-center" aria-hidden="true">
          <span className="subtle">{centerLabel}</span>
          <strong>{money(total)}</strong>
        </div>
      </div>
      <ul className="legend">
        {listed.map((s) => (
          <li key={s.key} {...pressable(pick(s))}>
            <span className="swatch" style={{ background: s.color }} />
            <span>{s.label}</span>
            <span className="value">{money(s.value_cents)}</span>
            <span className="share">{percent(s.value_cents / total)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Where your net worth sits, by asset type (fixed colors per type). */
export function AllocationDonut({ worth }: { worth: NetWorth }) {
  const slices = worth.by_type.map((t) => ({
    key: t.asset_type,
    label: assetMeta(t.asset_type).label,
    value_cents: t.value_cents,
    color: seriesVar(assetMeta(t.asset_type).slot),
  }));
  return <Donut slices={slices} centerLabel="Total" />;
}

/**
 * Spending by category as a donut. ``colorOrder`` is the user's biggest
 * categories of all time (covered ones excluded); the first five get the five
 * series colors for good, the rest of the month is "Other", and covered costs
 * (e.g. rent a family member pays) are one light-gray "Covered" slice. Clicking a
 * slice ticks that category; "Other" and "Covered" tick everything inside them.
 */
export function CategoryDonut({
  report,
  colorOrder,
  covered,
  coveredLabel,
  hideCovered,
  focus = [],
  onSelect,
}: {
  report: CategoryReport;
  colorOrder: string[];
  covered: string[];
  coveredLabel: string;
  hideCovered: boolean;
  focus?: string[]; // chosen categories, biggest of all time first; empty = everything
  onSelect?: SelectCategories;
}) {
  const isCovered = new Set(covered.map((c) => c.toLowerCase()));
  const byName = new Map(report.items.map((i) => [i.category.toLowerCase(), i.total_cents]));
  if (focus.length) {
    return (
      <Donut
        slices={focusSlices(focus, byName, isCovered)}
        centerLabel="Chosen"
        listEmpty
        emptyNote="No spending in these categories this month."
        onSelect={onSelect}
      />
    );
  }
  const colored = colorOrder.filter((c) => !isCovered.has(c.toLowerCase())).slice(0, 5);

  const slices: Slice[] = colored.map((name, i) => ({
    key: name,
    label: name,
    value_cents: byName.get(name.toLowerCase()) ?? 0,
    color: seriesVar(i + 1),
    select: [name],
  }));
  const coloredSet = new Set(colored.map((c) => c.toLowerCase()));
  const other: string[] = [];
  const coveredHere: string[] = [];
  for (const item of report.items) {
    const key = item.category.toLowerCase();
    if (isCovered.has(key)) coveredHere.push(item.category);
    else if (!coloredSet.has(key)) other.push(item.category);
  }
  const sum = (names: string[]) => names.reduce((total, n) => total + (byName.get(n.toLowerCase()) ?? 0), 0);
  slices.push({ key: "__other", label: "Other", value_cents: sum(other), color: "var(--other)", select: other });
  if (!hideCovered) {
    slices.push({
      key: "__covered", label: coveredLabel, value_cents: sum(coveredHere), color: "var(--covered)", select: coveredHere,
    });
  }
  return <Donut slices={slices} centerLabel="Spent" onSelect={onSelect} />;
}

/**
 * Slices for just the chosen categories. Colors go by position (first chosen
 * = series 1, next = series 2, ...), NOT each category's color in the full
 * chart: the palette was checked for colorblind safety only between
 * neighboring slots, and a hand-picked subset of fixed colors can put two
 * look-alikes (e.g. orange and yellow) side by side. Six colors at most, all
 * neighbors that passed the check; anything beyond goes into a gray "Other".
 * Categories with nothing this month aren't in the ring (they'd leave a gap
 * between two unchecked neighbors), so they get no color, just a $0 legend row.
 */
const FOCUS_COLORS = 6;

function focusSlices(focus: string[], byName: Map<string, number>, isCovered: Set<string>): Slice[] {
  const value = (name: string) => byName.get(name.toLowerCase()) ?? 0;
  const label = (name: string) => (isCovered.has(name.toLowerCase()) ? `${name} (covered)` : name);
  const spent = focus.filter((name) => value(name) > 0);
  const colored = spent.slice(0, FOCUS_COLORS);
  const rest = spent.slice(FOCUS_COLORS);
  const slices: Slice[] = colored.map((name, i) => ({
    key: name, label: label(name), value_cents: value(name), color: seriesVar(i + 1), select: [name],
  }));
  if (rest.length) {
    slices.push({
      key: "__other",
      label: rest.length <= 2 ? `Other (${rest.join(", ")})` : `${rest.length} others`,
      value_cents: rest.reduce((sum, name) => sum + value(name), 0),
      color: "var(--other)",
      select: rest,
    });
  }
  for (const name of focus.filter((n) => value(n) <= 0)) {
    slices.push({ key: name, label: label(name), value_cents: 0, color: "var(--fill-strong)", select: [name] });
  }
  return slices;
}

/** One category broken down by purchase, colored by position like ``focusSlices``. */
export function PurchaseDonut({ report }: { report: PurchaseReport }) {
  const spent = report.items.filter((i) => i.total_cents > 0);
  const colored = spent.slice(0, FOCUS_COLORS);
  const rest = spent.slice(FOCUS_COLORS);
  const slices: Slice[] = colored.map((i, n) => ({
    key: i.description,
    label: i.count > 1 ? `${i.description} ×${i.count}` : i.description,
    value_cents: i.total_cents,
    color: seriesVar(n + 1),
  }));
  if (rest.length) {
    slices.push({
      key: "__other",
      label: `${rest.length} other purchase${rest.length > 1 ? "s" : ""}`,
      value_cents: rest.reduce((sum, i) => sum + i.total_cents, 0),
      color: "var(--other)",
    });
  }
  return <Donut slices={slices} centerLabel={report.category} emptyNote={`No purchases in ${report.category} this month.`} />;
}

/* ------------------------------------------------------------------ table twin for charts */

function TableView({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <details className="table-view">
      <summary>Show as table</summary>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {headers.map((h, i) => (
                <th key={h} className={i > 0 ? "right" : undefined}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row[0]}>
                {row.map((cell, i) => (
                  <td key={i} className={i > 0 ? "right num" : undefined}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
