import { useState, type FormEvent, type KeyboardEvent } from "react";
import { api, type NetWorthLine } from "../api";
import { AllocationDonut } from "../components/charts";
import { HoldingForm } from "../components/forms";
import { Sheet } from "../components/Sheet";
import { assetMeta, money, quantity, seriesVar } from "../format";
import { useAsync } from "../hooks";
import { AssetIcon } from "../icons";

export function Holdings({ version, onChanged }: { version: number; onChanged: () => void }) {
  const worth = useAsync(api.netWorth, [version]);

  return (
    <>
      <h1 className="page-title">Holdings</h1>
      <div className="grid grid-3">
        <div className="stack span-2" style={{ alignContent: "start" }}>
          <div className={`card ${worth.loading && worth.data ? "refreshing" : ""}`}>
            <div className="eyebrow">Net worth</div>
            {worth.error && <p className="message error">{worth.error}</p>}
            {worth.data ? (
              <>
                <div className="hero">{money(worth.data.total_cents)}</div>
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

          <div className={`card ${worth.loading && worth.data ? "refreshing" : ""}`}>
            <div className="card-head">
              <h2 className="card-title">Everything you own</h2>
              <span className="card-subtitle">Click one to edit it · prices refresh every 15 minutes</span>
            </div>
            {worth.data && <HoldingsTable lines={worth.data.lines} onChanged={onChanged} />}
          </div>
        </div>

        <div className="card" style={{ alignSelf: "start" }}>
          <div className="card-head">
            <h2 className="card-title">Add a holding</h2>
          </div>
          <HoldingForm onSaved={onChanged} />
        </div>
      </div>
    </>
  );
}

const isPriced = (line: NetWorthLine) => line.asset_type !== "cash" && line.asset_type !== "other";

function HoldingsTable({ lines, onChanged }: { lines: NetWorthLine[]; onChanged: () => void }) {
  const [editing, setEditing] = useState<NetWorthLine | null>(null);

  if (!lines.length) return <p className="empty">Nothing here yet. Add your first holding on the right.</p>;

  const onKey = (event: KeyboardEvent, line: NetWorthLine) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setEditing(line);
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
                onClick={() => setEditing(line)}
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
    </div>
  );
}

function EditHoldingSheet({ line, onClose, onSaved }: { line: NetWorthLine; onClose: () => void; onSaved: () => void }) {
  const priced = isPriced(line);
  const hasSymbol = line.asset_type === "stock" || line.asset_type === "crypto";
  const [name, setName] = useState(line.name);
  const [symbol, setSymbol] = useState(line.symbol ?? "");
  const [qty, setQty] = useState(String(line.quantity));
  const [value, setValue] = useState(((line.manual_value_cents ?? 0) / 100).toFixed(2));
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.updateHolding(line.id, {
        name,
        ...(hasSymbol ? { symbol } : {}),
        ...(priced ? { quantity: Number(qty.replace(/,/g, "")) } : { value }),
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
          <label className="field">
            <span>{unit}</span>
            <input type="text" inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} required />
          </label>
        ) : (
          <label className="field">
            <span>Current value</span>
            <div className="money-input">
              <i>$</i>
              <input type="text" inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} required />
            </div>
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
