import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CategoryReport, MonthRow, NetWorth, Snapshot } from "../api";
import { assetMeta, dateLabel, dateShort, money, moneyAxis, monthLabel, monthShort, percent, seriesVar } from "../format";
import { useChartTheme } from "../hooks";

const axisTick = (color: string) => ({ fill: color, fontSize: 12 });

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
          <YAxis tickFormatter={moneyAxis} tickLine={false} axisLine={false} tick={axisTick(t.muted)} width={58} />
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
            width={58}
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

/* ------------------------------------------------------------------ spending by category
   Ranked bars instead of a pie: lengths are much easier to compare than
   slice angles, and every bar carries its own value and share. */

const MAX_CATEGORY_ROWS = 8;

export function CategoryBars({ report }: { report: CategoryReport }) {
  if (!report.items.length) return <p className="chart-note">No spending recorded for this period.</p>;

  let items = report.items;
  if (items.length > MAX_CATEGORY_ROWS) {
    const head = items.slice(0, MAX_CATEGORY_ROWS - 1);
    const rest = items.slice(MAX_CATEGORY_ROWS - 1);
    const restTotal = rest.reduce((sum, i) => sum + i.total_cents, 0);
    items = [
      ...head,
      { category: `Other (${rest.length})`, total_cents: restTotal, share: restTotal / report.total_cents },
    ];
  }
  const largest = Math.max(...items.map((i) => i.total_cents));

  return (
    <ol className="rank-bars" aria-label="Spending by category">
      {items.map((item) => (
        <li key={item.category} title={`${item.category}: ${money(item.total_cents)} (${percent(item.share)})`}>
          <span className="label">{item.category}</span>
          <span className="track" aria-hidden="true">
            <span className="fill" style={{ width: `${(item.total_cents / largest) * 100}%` }} />
          </span>
          <span className="value">{money(item.total_cents)}</span>
          <span className="share">{percent(item.share)}</span>
        </li>
      ))}
    </ol>
  );
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
