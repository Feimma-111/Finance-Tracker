import { Fragment, useState, type FormEvent, type KeyboardEvent } from "react";
import {
  api, type AssetType, type Change, type HoldingsReview, type NetWorthLine, type Period, type PortfolioHolding, type Position,
  type Transaction,
} from "../api";
import { AiStatusLine, isOnline } from "../components/AiParts";
import { AllocationDonut, NetWorthChart } from "../components/charts";
import { HoldingForm } from "../components/forms";
import { Sheet } from "../components/Sheet";
import { assetMeta, currencySymbol, dateCompact, dateLabel, money, moneyIn, quantity, seriesVar, signedMoney } from "../format";
import { useAsync, useNarrow } from "../hooks";
import { AssetIcon } from "../icons";
import { DateInput } from "../components/DateInput";
import { EditTransactionSheet } from "../components/TransactionList";

export function Holdings({ version, onChanged }: { version: number; onChanged: () => void }) {
  const worth = useAsync(api.netWorth, [version]);
  const [editing, setEditing] = useState<NetWorthLine | null>(null);
  const [addingTo, setAddingTo] = useState<NetWorthLine | null>(null); // another purchase of this investment
  const edit = (id: number) => setEditing(worth.data?.lines.find((l) => l.id === id) ?? null);
  const hasCash = !!worth.data?.lines.some((l) => l.asset_type === "cash");
  const hasInvestments = !!worth.data?.lines.some(isPriced);

  return (
    <>
      <h1 className="page-title">Holdings</h1>
      <div className="grid grid-3">
        <div className="stack span-2" style={{ alignContent: "start" }}>
          <div className={`card ${worth.loading && worth.data ? "refreshing" : ""}`}>
            <div className="worth-head">
              <div>
                <div className="eyebrow">Net worth</div>
                {worth.data && <div className="hero">{money(worth.data.total_cents)}</div>}
              </div>
              {worth.data && hasCash && (
                <div className="liquid" title="Every cash account together: what you could spend right now">
                  <div className="eyebrow">Liquid</div>
                  <div className="tile-value">{money(worth.data.liquid_cents)}</div>
                </div>
              )}
            </div>
            {worth.error && <p className="message error">{worth.error}</p>}
            {worth.data ? (
              <>
                {!worth.data.complete && (
                  <p className="message error">Some holdings couldn't be priced and aren't in this total.</p>
                )}
                <div style={{ marginTop: 12 }}>
                  <AllocationDonut worth={worth.data} />
                </div>
              </>
            ) : (
              !worth.error && <div className="hero subtle">…</div>
            )}
          </div>

          {hasInvestments && <Investments version={version} onEdit={edit} />}
          {hasInvestments && <HoldingsAi />}

          <div className={`card ${worth.loading && worth.data ? "refreshing" : ""}`}>
            <div className="card-head">
              <h2 className="card-title">Everything you own</h2>
              <span className="card-subtitle">Click one to see its purchases or activity · prices refresh every 15 minutes</span>
            </div>
            {worth.data && (
              <HoldingsTable lines={worth.data.lines} onEdit={setEditing} onAddPurchase={setAddingTo} onChanged={onChanged} version={version} />
            )}
          </div>
        </div>

        <div className="card" style={{ alignSelf: "start" }}>
          <div className="card-head">
            <h2 className="card-title">Add a holding</h2>
          </div>
          <HoldingForm onSaved={onChanged} />
        </div>
      </div>
      {addingTo && (
        <PurchaseSheet
          of={addingTo}
          onClose={() => setAddingTo(null)}
          onSaved={() => {
            setAddingTo(null);
            onChanged();
          }}
        />
      )}
      {editing && (
        <EditHoldingSheet
          line={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            onChanged();
          }}
        />
      )}
    </>
  );
}

const isPriced = (line: { asset_type: string }) => line.asset_type !== "cash" && line.asset_type !== "other";

/* ------------------------------------------------------------------ investments */

const PERIODS: { id: Period; label: string; long: string }[] = [
  { id: "1W", label: "1W", long: "past week" },
  { id: "1M", label: "1M", long: "past month" },
  { id: "3M", label: "3M", long: "past 3 months" },
  { id: "YTD", label: "YTD", long: "this year" },
  { id: "1Y", label: "1Y", long: "past year" },
  { id: "ALL", label: "All", long: "since you bought" },
];

/** "+$72.20 (+2.1%)", green when up and red when down (it's money you own). */
function ChangeText({ change, suffix }: { change?: Change | null; suffix?: string }) {
  if (!change) return <span className="subtle">—</span>;
  const up = change.change_cents > 0;
  const down = change.change_cents < 0;
  return (
    <span className={up ? "delta-good" : down ? "delta-bad" : undefined}>
      <span style={{ whiteSpace: "nowrap" }}>
        {up ? "▲ " : down ? "▼ " : ""}
        {signedMoney(change.change_cents)}
      </span>
      {change.pct !== null && ` (${change.pct > 0 ? "+" : ""}${change.pct.toFixed(1)}%)`}
      {suffix && <span className="subtle"> {suffix}</span>}
    </span>
  );
}

function rememberedPeriod(): Period {
  try {
    const saved = localStorage.getItem("finance-tracker:portfolio-period");
    if (PERIODS.some((p) => p.id === saved)) return saved as Period;
  } catch {
    // ignore
  }
  return "1M";
}

function Investments({ version, onEdit }: { version: number; onEdit: (id: number) => void }) {
  const [period, setPeriodState] = useState<Period>(rememberedPeriod);
  const setPeriod = (p: Period) => {
    setPeriodState(p);
    try {
      localStorage.setItem("finance-tracker:portfolio-period", p);
    } catch {
      // ignore
    }
  };
  const report = useAsync(() => api.portfolio(period), [period, version]);
  const info = PERIODS.find((p) => p.id === period)!;
  const data = report.data;
  const missingCost = !!data?.holdings.some((h) => h.value_cents !== null && h.cost_basis_cents === null);

  return (
    <div className={`card ${report.loading && data ? "refreshing" : ""}`}>
      <div className="card-head">
        <h2 className="card-title">Investments</h2>
        <div className="card-action">
          <div className="segmented" role="group" aria-label="Period">
            {PERIODS.map((p) => (
              <button key={p.id} type="button" aria-pressed={period === p.id} onClick={() => setPeriod(p.id)}>
                {p.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      {report.error && <p className="message error">{report.error}</p>}
      {data && (
        <>
          <div className="investment-summary">
            <div>
              <div className="hero">{money(data.value_cents)}</div>
              <div className="delta"><ChangeText change={data.period_change} suffix={info.long} /></div>
            </div>
            <dl className="investment-stats">
              <div>
                <dt>Today</dt>
                <dd><ChangeText change={data.today} /></dd>
              </div>
              <div>
                <dt>Since you bought</dt>
                <dd>{data.total ? <ChangeText change={data.total} /> : <span className="subtle">add what you paid</span>}</dd>
              </div>
              {data.cost_cents !== null && (
                <div>
                  <dt>You paid</dt>
                  <dd className="num">{money(data.cost_cents)}</dd>
                </div>
              )}
            </dl>
          </div>
          <NetWorthChart history={data.series.map((p) => ({ date: p.date, total_cents: p.value_cents }))} />
          <InvestmentTable positions={data.positions} lots={data.holdings} periodLabel={info.label} onEdit={onEdit} />
          {missingCost && (
            <p className="hint" style={{ margin: "10px 0 0" }}>
              Open an investment, click a purchase, and add when you bought it and the price you paid to see its gain.
            </p>
          )}
        </>
      )}
    </div>
  );
}

/** "4 shares", "0.25 oz". */
const amountOf = (type: string, n: number) => `${quantity(n)} ${type === "stock" ? "shares" : type === "gold" ? "oz" : "units"}`;
/** All purchases of the same investment share this (matches the server's position key). */
const positionKey = (h: { asset_type: string; symbol: string | null; name: string }) =>
  `${h.asset_type}:${(h.symbol ?? h.name).toUpperCase()}`;
/** Props for a row that's clickable and also reachable by keyboard. */
const pressRow = (onPress: () => void) => ({
  tabIndex: 0,
  role: "button" as const,
  onClick: onPress,
  onKeyDown: (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onPress();
    }
  },
});

/** One row per investment; open it to see each purchase's gains, and click one to edit it. */
function InvestmentTable({
  positions, lots, periodLabel, onEdit,
}: {
  positions: Position[]; lots: PortfolioHolding[]; periodLabel: string; onEdit: (id: number) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const byId = new Map(lots.map((l) => [l.id, l]));
  return (
    <div className="table-wrap" style={{ marginTop: 14 }}>
      <table className="clickable-rows">
        <thead>
          <tr>
            <th>Investment</th>
            <th className="right">Value</th>
            <th className="right hide-narrow">Today</th>
            <th className="right">{periodLabel}</th>
            <th className="right hide-narrow">Since bought</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => {
            const isOpen = open === p.key;
            const purchases = p.lot_ids.map((id) => byId.get(id)).filter((l): l is PortfolioHolding => !!l)
              .sort((a, b) => (b.bought_on ?? "").localeCompare(a.bought_on ?? ""));
            return (
              <Fragment key={p.key}>
                <tr className={isOpen ? "open" : undefined} aria-expanded={isOpen} aria-label={`${p.name}: show purchases`}
                  {...pressRow(() => setOpen(isOpen ? null : p.key))}>
                  <td>
                    <div className="holding-name">
                      <AssetIcon type={p.asset_type} size={28} />
                      <div>
                        {p.name}
                        <div className="subtle">
                          {amountOf(p.asset_type, p.quantity)}
                          {p.avg_price != null && ` · ${money(Math.round(p.avg_price * 100))} avg`}
                          {p.lot_ids.length > 1 && ` · ${p.lot_ids.length} purchases`}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="right num">{money(p.value_cents)}</td>
                  <td className="right num hide-narrow"><ChangeText change={p.today} /></td>
                  <td className="right num"><ChangeText change={p.period} /></td>
                  <td className="right num hide-narrow" style={{ whiteSpace: "nowrap" }}>
                    <ChangeText change={p.total} />
                    <span className={`row-chevron disclosure ${isOpen ? "open" : ""}`} aria-hidden="true">›</span>
                  </td>
                </tr>
                {isOpen && purchases.map((lot) => (
                  <tr key={lot.id} className="lot-row" aria-label={`Edit this purchase of ${p.name}`} {...pressRow(() => onEdit(lot.id))}>
                    <td>
                      <div className="lot-label">
                        {lot.bought_on ? `Bought ${dateCompact(lot.bought_on)}` : "Purchase date not set"}
                        <div className="subtle">
                          {amountOf(lot.asset_type, lot.quantity)}
                          {lot.avg_price != null && ` at ${money(Math.round(lot.avg_price * 100))}`}
                        </div>
                      </div>
                    </td>
                    <td className="right num">{lot.value_cents !== null ? money(lot.value_cents) : "n/a"}</td>
                    <td className="right num hide-narrow"><ChangeText change={lot.today} /></td>
                    <td className="right num"><ChangeText change={lot.period} /></td>
                    <td className="right num hide-narrow" style={{ whiteSpace: "nowrap" }}>
                      <ChangeText change={lot.total} />
                      <span className="row-chevron" aria-hidden="true">›</span>
                    </td>
                  </tr>
                ))}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ------------------------------------------------------------------ AI on your investments
   Kept in sessionStorage like the other AI panels: it survives a reload and
   is gone when the tab closes. It describes; it never tells you what to buy. */

const AI_KEY = "finance-tracker:holdings-review";

function savedReview(): HoldingsReview | null {
  try {
    return JSON.parse(sessionStorage.getItem(AI_KEY) ?? "null");
  } catch {
    return null;
  }
}

function HoldingsAi() {
  const status = useAsync(api.aiStatus, []);
  const [result, setResult] = useState<HoldingsReview | null>(savedReview);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const online = isOnline(status.data);

  async function analyze() {
    setBusy(true);
    setError(null);
    try {
      const next = await api.holdingsReview();
      setResult(next);
      try {
        sessionStorage.setItem(AI_KEY, JSON.stringify(next));
      } catch {
        // storage blocked: it still shows until reload
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const section = (title: string, items: string[]) =>
    items.length > 0 && (
      <div>
        <h3 className="ai-heading">{title}</h3>
        <ul>{items.map((item, i) => <li key={i}>{item}</li>)}</ul>
      </div>
    );

  return (
    <div className="card ai-card">
      <div className="card-head">
        <h2 className="card-title">AI on your investments</h2>
        <span className="card-subtitle">Your holdings and the market, from your PC</span>
        <div className="card-action">
          {online && (
            <button className="btn btn-small btn-primary" onClick={analyze} disabled={busy}>
              {busy ? "Thinking…" : result ? "Analyze again" : "Analyze my investments"}
            </button>
          )}
        </div>
      </div>
      <AiStatusLine status={status} />
      {busy && <p className="hint">Checking prices and news, then asking the model on your PC. This takes 10–40 seconds.</p>}
      {error && <p className="message error">{error}</p>}
      {result ? (
        <div className={`ai-review ${busy ? "refreshing" : ""}`} style={{ marginTop: 10 }}>
          <p className="ai-headline">{result.review.headline}</p>
          <div className="grid grid-2 ai-columns">
            {section("Your investments", result.review.holdings)}
            {section("The market", result.review.market)}
          </div>
          <div style={{ marginTop: 14 }}>{section("Worth keeping in mind", result.review.keep_in_mind)}</div>
          <p className="subtle ai-meta">
            Written {new Date(result.created_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
            {" "}by {result.model}. It describes; it doesn't tell you what to buy or sell. AI can make mistakes, and
            this isn't financial advice.
          </p>
          <details className="table-view">
            <summary>What the AI was shown</summary>
            <pre className="ai-facts">{result.facts}</pre>
          </details>
        </div>
      ) : (
        !busy && <p className="hint" style={{ margin: "8px 0 0" }}>
          The app works out your gains and the market's moves, adds this week's headlines about your holdings, and the
          model describes what's going on.
        </p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ everything you own
   Grouped by type with a subtotal each. An investment bought more than once
   is one row; opening it lists each purchase (click one to edit it). A cash
   account opens to what moved it (click a transaction to edit it). */

const TYPE_ORDER: AssetType[] = ["cash", "stock", "crypto", "gold", "other"];

/** A table row: one account / other holding, or one investment with all its purchases. */
interface Row {
  key: string;
  lines: NetWorthLine[];
}

function HoldingsTable({
  lines, onEdit, onAddPurchase, onChanged, version,
}: {
  lines: NetWorthLine[];
  onEdit: (line: NetWorthLine) => void;
  onAddPurchase: (of: NetWorthLine) => void;
  onChanged: () => void;
  version: number;
}) {
  const [open, setOpen] = useState<string | null>(null);
  // On phones the Price column is hidden; spanning it anyway would add a phantom column.
  const columns = useNarrow() ? 3 : 4;
  if (!lines.length) return <p className="empty">Nothing here yet. Add your first holding on the right.</p>;

  const groups = TYPE_ORDER.map((type) => {
    const ofType = lines.filter((l) => l.asset_type === type);
    const rows: Row[] = [];
    for (const line of ofType) {
      const key = isPriced(line) ? positionKey(line) : `holding:${line.id}`;
      const row = rows.find((r) => r.key === key);
      if (row) row.lines.push(line);
      else rows.push({ key, lines: [line] });
    }
    return { type, lines: ofType, rows };
  }).filter((g) => g.lines.length);

  return (
    <div className="table-wrap">
      <table className="clickable-rows holdings-table">
        <thead>
          <tr>
            <th>Holding</th>
            <th className="right">
              <span className="hide-narrow">Quantity</span>
              <span className="show-narrow">Qty</span>
            </th>
            <th className="right hide-narrow">Price</th>
            <th className="right">Value</th>
          </tr>
        </thead>
        {groups.map((group) => {
          const meta = assetMeta(group.type);
          const subtotal = group.lines.reduce((sum, l) => sum + (l.value_cents ?? 0), 0);
          return (
            <tbody key={group.type} className="holding-group">
              <tr className="group-row">
                <th colSpan={columns - 1} scope="rowgroup">
                  <span className="swatch" style={{ background: seriesVar(meta.slot) }} />
                  {meta.label}
                  <span className="subtle"> · {group.rows.length}</span>
                </th>
                <th className="right num">{money(subtotal)}</th>
              </tr>
              {group.rows.map((row) => (
                <HoldingRow
                  key={row.key}
                  lines={row.lines}
                  columns={columns}
                  open={open === row.key}
                  onToggle={() => setOpen((current) => (current === row.key ? null : row.key))}
                  onEdit={onEdit}
                  onAddPurchase={onAddPurchase}
                  onChanged={onChanged}
                  version={version}
                />
              ))}
            </tbody>
          );
        })}
      </table>
    </div>
  );
}

function HoldingRow({
  lines, columns, open, onToggle, onEdit, onAddPurchase, onChanged, version,
}: {
  lines: NetWorthLine[];
  columns: number;
  open: boolean;
  onToggle: () => void;
  onEdit: (line: NetWorthLine) => void;
  onAddPurchase: (of: NetWorthLine) => void;
  onChanged: () => void;
  version: number;
}) {
  const line = lines[0];
  const priced = isPriced(line);
  const total = lines.every((l) => l.value_cents === null) ? null : lines.reduce((sum, l) => sum + (l.value_cents ?? 0), 0);
  const owned = lines.reduce((sum, l) => sum + l.quantity, 0);
  const note = lines.map((l) => l.note).find(Boolean);
  return (
    <>
      <tr
        aria-expanded={open}
        aria-label={`${line.name}: show ${priced ? "purchases" : "activity"}`}
        className={open ? "open" : undefined}
        {...pressRow(onToggle)}
      >
        <td>
          <div className="holding-name">
            <AssetIcon type={line.asset_type} size={32} />
            <div>
              {line.name}
              {line.symbol && line.symbol !== line.name && line.asset_type !== "gold" && (
                <span className="subtle"> · {line.symbol}</span>
              )}
              {lines.length > 1 && <div className="subtle">{lines.length} purchases</div>}
              {note && <div className="subtle">{note}</div>}
              {line.asset_type === "cash" && <BalanceNote line={line} />}
            </div>
          </div>
        </td>
        <td className="right num">{priced ? quantity(owned) : ""}</td>
        <td className="right num hide-narrow">
          {line.unit_price !== null
            ? `$${line.unit_price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
            : ""}
        </td>
        <td className="right num" style={{ whiteSpace: "nowrap" }}>
          {total !== null ? money(total) : <span className="subtle">n/a</span>}
          <span className={`row-chevron disclosure ${open ? "open" : ""}`} aria-hidden="true">›</span>
        </td>
      </tr>
      {open && (
        <tr className="activity-row">
          <td colSpan={columns}>
            {priced
              ? <Purchases lots={lines} onEdit={onEdit} onAdd={() => onAddPurchase(line)} />
              : <Activity line={line} onEdit={() => onEdit(line)} onChanged={onChanged} version={version} />}
          </td>
        </tr>
      )}
    </>
  );
}

/** An investment's purchases, newest first. Click one to edit it. */
function Purchases({ lots, onEdit, onAdd }: { lots: NetWorthLine[]; onEdit: (line: NetWorthLine) => void; onAdd: () => void }) {
  const sorted = [...lots].sort((a, b) => (b.bought_on ?? "").localeCompare(a.bought_on ?? ""));
  return (
    <div className="activity">
      <div className="activity-head">
        <strong>{lots.length > 1 ? `${lots.length} purchases` : "Purchase"}</strong>
        <button type="button" className="btn btn-small" onClick={onAdd}>Add another purchase</button>
      </div>
      <ol className="activity-list">
        {sorted.map((lot) => {
          const each = lot.cost_basis_cents !== null && lot.quantity ? Math.round(lot.cost_basis_cents / lot.quantity) : null;
          return (
            <li key={lot.id} className="activity-item pressable" aria-label={`Edit this purchase of ${lot.name}`} {...pressRow(() => onEdit(lot))}>
              <span className="activity-date">{lot.bought_on ? dateCompact(lot.bought_on) : "No date"}</span>
              <span className="activity-main">
                Bought {amountOf(lot.asset_type, lot.quantity)}
                {each !== null && ` at ${money(each)}`}
                {lot.value_cents !== null && <span className="subtle hide-narrow"> · worth {money(lot.value_cents)} now</span>}
              </span>
              <span className="num" style={{ whiteSpace: "nowrap" }}>
                {lot.cost_basis_cents !== null ? `paid ${money(lot.cost_basis_cents)}` : <span className="subtle">price not set</span>}
                <span className="row-chevron" aria-hidden="true">›</span>
              </span>
            </li>
          );
        })}
      </ol>
      <p className="hint" style={{ margin: 0 }}>Click a purchase to edit or remove it.</p>
    </div>
  );
}

/** A cash account's activity (newest first, in its own currency). Click a transaction to edit it. */
function Activity({ line, onEdit, onChanged, version }: { line: NetWorthLine; onEdit: () => void; onChanged: () => void; version: number }) {
  const activity = useAsync(() => api.holdingActivity(line.id), [line.id, version]);
  const [editingTx, setEditingTx] = useState<Transaction | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);
  const own = (cents: number) => moneyIn(cents, line.currency);
  const data = activity.data;
  const cash = line.asset_type === "cash";
  const openTransaction = (id: number) => {
    setOpenError(null);
    api.getTransaction(id).then(setEditingTx, (e: Error) => setOpenError(e.message));
  };
  // Where the balance was entered: after the items that came later, before the ones it already includes.
  const markerAt = data?.balance ? data.items.findIndex((i) => !i.counted) : -1;
  const marker = data?.balance && (
    <li key="balance" className="activity-item balance-marker">
      <span className="activity-date">{dateCompact(data.balance.date)}</span>
      <span className="activity-main">Balance set to {own(data.balance.amount_cents ?? 0)}</span>
      <span />
    </li>
  );

  return (
    <div className="activity">
      <div className="activity-head">
        <strong>{cash ? "Activity" : line.name}</strong>
        <button type="button" className="btn btn-small" onClick={onEdit}>Edit {cash ? "account" : "holding"}</button>
      </div>
      {activity.error && <p className="message error">{activity.error}</p>}
      {openError && <p className="message error">{openError}</p>}
      {data && cash && !data.items.length && !data.balance && (
        <p className="hint" style={{ margin: 0 }}>Nothing linked yet. When you add a transaction, choose this account under “Paid from”.</p>
      )}
      {data && (data.items.length > 0 || data.balance) && (
        <ol className="activity-list">
          {data.items.map((item, index) => {
            // Transactions open for editing; transfers are edited on the Transactions page.
            const editable = item.type === "expense" || item.type === "income";
            return (
              <Fragment key={`${item.type}-${item.id}`}>
                {index === markerAt && marker}
                <li
                  className={`activity-item ${item.counted ? "" : "settled"} ${editable ? "pressable" : ""}`}
                  {...(editable ? { ...pressRow(() => openTransaction(item.id)), "aria-label": `Edit ${item.description}` } : {})}
                >
                  <span className="activity-date">{item.date ? dateCompact(item.date) : "—"}</span>
                  <span className="activity-main">
                    {item.type === "bought" ? `Bought ${amountOf(line.asset_type, item.quantity ?? 0)}` : item.description}
                    {item.type === "transfer" && <span className="activity-tag">Transfer</span>}
                    {item.category && <span className="subtle"> · {item.category}</span>}
                  </span>
                  <span className={`num ${item.amount_cents !== null && item.amount_cents > 0 && item.type !== "bought" ? "amount-income" : ""}`}
                    style={{ whiteSpace: "nowrap" }}>
                    {item.amount_cents === null ? "" : item.type === "bought"
                      ? `paid ${money(item.amount_cents)}`
                      : `${item.amount_cents > 0 ? "+" : "−"}${own(Math.abs(item.amount_cents))}`}
                    {editable && <span className="row-chevron" aria-hidden="true">›</span>}
                  </span>
                </li>
              </Fragment>
            );
          })}
          {markerAt === -1 && marker}
        </ol>
      )}
      {data && cash && data.items.some((i) => !i.counted) && (
        <p className="hint" style={{ margin: 0 }}>Greyed items came before the balance was set, so they're already in it.</p>
      )}
      {editingTx && (
        <EditTransactionSheet
          tx={editingTx}
          onClose={() => setEditingTx(null)}
          onSaved={() => {
            setEditingTx(null);
            onChanged();
          }}
        />
      )}
    </div>
  );
}

/** Another purchase of an investment you already have: how much, when, at what price. */
function PurchaseSheet({ of, onClose, onSaved }: { of: NetWorthLine; onClose: () => void; onSaved: () => void }) {
  const [qty, setQty] = useState("");
  const [boughtOn, setBoughtOn] = useState("");
  const [price, setPrice] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.addHolding({
        asset_type: of.asset_type,
        name: of.name,
        symbol: of.symbol ?? undefined,
        quantity: Number(qty.replace(/,/g, "")),
        bought_on: boughtOn || undefined,
        avg_price: price.trim() || undefined,
      });
      onSaved();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  const unit = of.asset_type === "gold" ? "Troy ounces bought" : of.asset_type === "crypto" ? "Amount bought" : "Shares bought";
  return (
    <Sheet title={`Another purchase of ${of.name}`} onClose={onClose}>
      <form className="form" onSubmit={save}>
        <label className="field">
          <span>{unit}</span>
          <input type="text" inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} placeholder="0" required autoFocus />
        </label>
        <div className="field-row">
          <label className="field">
            <span>Bought on</span>
            <DateInput value={boughtOn} onChange={setBoughtOn} />
          </label>
          <label className="field">
            <span>Price paid each</span>
            <div className="money-input">
              <i>$</i>
              <input type="text" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} placeholder="0.00" />
            </div>
          </label>
        </div>
        <p className="hint" style={{ margin: 0 }}>It joins {of.name}'s row, with its own gain from this date and price.</p>
        {error && <p className="message error" style={{ margin: 0 }}>{error}</p>}
        <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? "Adding…" : "Add purchase"}</button>
      </form>
    </Sheet>
  );
}

/** "NT$31,650 · updated Nov 22 · −NT$350 since" -- in the account's own currency. */
function BalanceNote({ line }: { line: NetWorthLine }) {
  const foreign = line.currency !== "USD";
  const own = (cents: number) => moneyIn(cents, line.currency);
  const balance = foreign && line.balance_cents !== null ? `${own(line.balance_cents)} · ` : "";
  if (!line.balance_as_of) return <div className="subtle">{balance}Update the balance to start following it</div>;
  const change = line.balance_change_cents;
  return (
    <div className="subtle">
      {balance}Updated {dateLabel(line.balance_as_of)}
      {change !== 0 && ` · ${change > 0 ? "+" : ""}${own(change)} since`}
    </div>
  );
}

function EditHoldingSheet({ line, onClose, onSaved }: { line: NetWorthLine; onClose: () => void; onSaved: () => void }) {
  const priced = isPriced(line);
  const cash = line.asset_type === "cash";
  const hasSymbol = line.asset_type === "stock" || line.asset_type === "crypto";
  const [name, setName] = useState(line.name);
  const [symbol, setSymbol] = useState(line.symbol ?? "");
  const [qty, setQty] = useState(String(line.quantity));
  // Cash shows the balance now (with linked transactions), in the account's
  // own currency; saving a new one makes that the starting point.
  const startValue = (((cash ? line.balance_cents : line.manual_value_cents) ?? 0) / 100).toFixed(2);
  const [value, setValue] = useState(startValue);
  const [boughtOn, setBoughtOn] = useState(line.bought_on ?? "");
  const [avgPrice, setAvgPrice] = useState(
    line.cost_basis_cents !== null && line.quantity ? (line.cost_basis_cents / 100 / line.quantity).toFixed(2) : "",
  );
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const originalValue = startValue;

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.updateHolding(line.id, {
        name,
        ...(hasSymbol ? { symbol } : {}),
        ...(priced
          ? { quantity: Number(qty.replace(/,/g, "")), bought_on: boughtOn, avg_price: avgPrice }
          // Only send the balance if it changed, so saving a rename doesn't reset the "as of" date.
          : value !== originalValue ? { value } : {}),
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
      await api.removeHolding(line.id);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  const unit = line.asset_type === "gold" ? "Troy ounces" : line.asset_type === "crypto" ? "Amount owned" : "Shares";
  return (
    <Sheet title={priced ? `Edit this purchase of ${line.name}` : `Edit ${line.name}`} onClose={onClose}>
      <form className="form" onSubmit={save}>
        <label className="field">
          <span>Name</span>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        {hasSymbol && (
          <label className="field">
            <span>Symbol</span>
            <input type="text" value={symbol} onChange={(e) => setSymbol(e.target.value)} autoCapitalize="characters" required />
          </label>
        )}
        {priced ? (
          <>
            <label className="field">
              <span>{unit}</span>
              <input type="text" inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} required />
            </label>
            <div className="field-row">
              <label className="field">
                <span>Bought on</span>
                <DateInput value={boughtOn} onChange={setBoughtOn} />
              </label>
              <label className="field">
                <span>Price paid each</span>
                <div className="money-input">
                  <i>$</i>
                  <input type="text" inputMode="decimal" value={avgPrice} onChange={(e) => setAvgPrice(e.target.value)} placeholder="per unit" />
                </div>
              </label>
            </div>
            <p className="hint" style={{ margin: 0 }}>
              Bought more later? Add it as another purchase instead. Leave both blank to stop tracking this one's gain.
            </p>
          </>
        ) : (
          <label className="field">
            <span>{cash ? "Balance today" : "Current value"}</span>
            <div className="money-input">
              <i>{currencySymbol(line.currency)}</i>
              <input type="text" inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} required />
            </div>
            {cash && (
              <span className="hint">
                {line.balance_as_of ? `Includes linked transactions since ${dateLabel(line.balance_as_of)}. ` : ""}
                Change it to match your bank, and it'll follow your transactions from today.
              </span>
            )}
          </label>
        )}
        {error && <p className="message error" style={{ margin: 0 }}>{error}</p>}
        <button className="btn btn-primary" type="submit" disabled={busy}>Save</button>
        <div className="sheet-danger">
          {confirmRemove ? (
            <>
              <span className="subtle">Remove {priced ? "this purchase" : line.name}?</span>
              <button type="button" className="btn btn-small btn-danger" onClick={remove} disabled={busy}>Remove</button>
              <button type="button" className="btn btn-small" onClick={() => setConfirmRemove(false)}>Keep</button>
            </>
          ) : (
            <button type="button" className="btn-link danger-link" onClick={() => setConfirmRemove(true)}>
              {priced ? "Remove this purchase" : "Remove holding"}
            </button>
          )}
        </div>
      </form>
    </Sheet>
  );
}
