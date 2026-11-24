import { useState, type FormEvent, type KeyboardEvent } from "react";
import { api, type Change, type HoldingsReview, type NetWorthLine, type Period, type PortfolioHolding } from "../api";
import { AiStatusLine, isOnline } from "../components/AiParts";
import { AllocationDonut, NetWorthChart } from "../components/charts";
import { HoldingForm } from "../components/forms";
import { Sheet } from "../components/Sheet";
import { assetMeta, currencySymbol, dateLabel, money, moneyIn, quantity, seriesVar, signedMoney } from "../format";
import { useAsync } from "../hooks";
import { AssetIcon } from "../icons";

export function Holdings({ version, onChanged }: { version: number; onChanged: () => void }) {
  const worth = useAsync(api.netWorth, [version]);
  const [editing, setEditing] = useState<NetWorthLine | null>(null);
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
              <span className="card-subtitle">Click one to edit it · prices refresh every 15 minutes</span>
            </div>
            {worth.data && <HoldingsTable lines={worth.data.lines} onEdit={setEditing} />}
          </div>
        </div>

        <div className="card" style={{ alignSelf: "start" }}>
          <div className="card-head">
            <h2 className="card-title">Add a holding</h2>
          </div>
          <HoldingForm onSaved={onChanged} />
        </div>
      </div>
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
          <InvestmentTable rows={data.holdings} periodLabel={info.label} onEdit={onEdit} />
          {missingCost && (
            <p className="hint" style={{ margin: "10px 0 0" }}>
              Click an investment and add when you bought it and the price you paid to see its gain since buying.
            </p>
          )}
        </>
      )}
    </div>
  );
}

function InvestmentTable({ rows, periodLabel, onEdit }: { rows: PortfolioHolding[]; periodLabel: string; onEdit: (id: number) => void }) {
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
          {rows.map((h) => (
            <tr key={h.id} tabIndex={0} role="button" aria-label={`Edit ${h.name}`} onClick={() => onEdit(h.id)}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onEdit(h.id))}>
              <td>
                <div className="holding-name">
                  <AssetIcon type={h.asset_type} size={28} />
                  <div>
                    {h.name}
                    <div className="subtle">
                      {quantity(h.quantity)} {h.asset_type === "gold" ? "oz" : h.asset_type === "stock" ? "shares" : ""}
                      {h.avg_price != null && ` · paid ${money(Math.round(h.avg_price * 100))} avg`}
                    </div>
                  </div>
                </div>
              </td>
              <td className="right num">{h.value_cents !== null ? money(h.value_cents) : <span className="subtle">n/a</span>}</td>
              <td className="right num hide-narrow"><ChangeText change={h.today} /></td>
              <td className="right num"><ChangeText change={h.period} /></td>
              <td className="right num hide-narrow"><ChangeText change={h.total} /></td>
            </tr>
          ))}
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

/* ------------------------------------------------------------------ everything you own */

function HoldingsTable({ lines, onEdit }: { lines: NetWorthLine[]; onEdit: (line: NetWorthLine) => void }) {
  if (!lines.length) return <p className="empty">Nothing here yet. Add your first holding on the right.</p>;

  const onKey = (event: KeyboardEvent, line: NetWorthLine) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onEdit(line);
    }
  };

  return (
    <div className="table-wrap">
      <table className="clickable-rows">
        <thead>
          <tr>
            <th>Holding</th>
            <th className="hide-narrow">Type</th>
            <th className="right">
              <span className="hide-narrow">Quantity</span>
              <span className="show-narrow">Qty</span>
            </th>
            <th className="right hide-narrow">Price</th>
            <th className="right">Value</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => {
            const meta = assetMeta(line.asset_type);
            return (
              <tr
                key={line.id}
                tabIndex={0}
                role="button"
                aria-label={`Edit ${line.name}`}
                onClick={() => onEdit(line)}
                onKeyDown={(e) => onKey(e, line)}
              >
                <td>
                  <div className="holding-name">
                    <AssetIcon type={line.asset_type} size={32} />
                    <div>
                      {line.name}
                      {line.symbol && line.symbol !== line.name && line.asset_type !== "gold" && (
                        <span className="subtle"> · {line.symbol}</span>
                      )}
                      {line.note && <div className="subtle">{line.note}</div>}
                      {line.asset_type === "cash" && <BalanceNote line={line} />}
                    </div>
                  </div>
                </td>
                <td className="hide-narrow" style={{ whiteSpace: "nowrap" }}>
                  <span className="swatch" style={{ background: seriesVar(meta.slot), marginRight: 8, verticalAlign: -1 }} />
                  {meta.label}
                </td>
                <td className="right num">{isPriced(line) ? quantity(line.quantity) : ""}</td>
                <td className="right num hide-narrow">
                  {line.unit_price !== null
                    ? `$${line.unit_price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                    : ""}
                </td>
                <td className="right num" style={{ whiteSpace: "nowrap" }}>
                  {line.value_cents !== null ? money(line.value_cents) : <span className="subtle">n/a</span>}
                  <span className="row-chevron" aria-hidden="true">›</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
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
    <Sheet title={`Edit ${line.name}`} onClose={onClose}>
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
                <input type="date" value={boughtOn} onChange={(e) => setBoughtOn(e.target.value)} />
              </label>
              <label className="field">
                <span>Average price paid</span>
                <div className="money-input">
                  <i>$</i>
                  <input type="text" inputMode="decimal" value={avgPrice} onChange={(e) => setAvgPrice(e.target.value)} placeholder="per unit" />
                </div>
              </label>
            </div>
            <p className="hint" style={{ margin: 0 }}>
              Bought more later? Use your average price and the first date. Leave both blank to stop tracking gains.
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
              <span className="subtle">Remove {line.name}?</span>
              <button type="button" className="btn btn-small btn-danger" onClick={remove} disabled={busy}>Remove</button>
              <button type="button" className="btn btn-small" onClick={() => setConfirmRemove(false)}>Keep</button>
            </>
          ) : (
            <button type="button" className="btn-link danger-link" onClick={() => setConfirmRemove(true)}>
              Remove holding
            </button>
          )}
        </div>
      </form>
    </Sheet>
  );
}
