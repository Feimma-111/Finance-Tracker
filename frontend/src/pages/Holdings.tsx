import { useState } from "react";
import { api, type NetWorthLine } from "../api";
import { Allocation } from "../components/charts";
import { HoldingForm } from "../components/forms";
import { assetMeta, money, quantity, seriesVar } from "../format";
import { useAsync } from "../hooks";

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
                <div style={{ marginTop: 16 }}>
                  <Allocation worth={worth.data} />
                </div>
              </>
            ) : (
              !worth.error && <div className="hero subtle">…</div>
            )}
          </div>

          <div className={`card ${worth.loading && worth.data ? "refreshing" : ""}`}>
            <div className="card-head">
              <h2 className="card-title">Everything you own</h2>
              <span className="card-subtitle">Market prices refresh every 15 minutes</span>
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

function HoldingsTable({ lines, onChanged }: { lines: NetWorthLine[]; onChanged: () => void }) {
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [confirming, setConfirming] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!lines.length) return <p className="empty">Nothing here yet. Add your first holding on the right.</p>;

  const priced = (line: NetWorthLine) => line.asset_type !== "cash" && line.asset_type !== "other";

  async function save(line: NetWorthLine) {
    setError(null);
    try {
      if (priced(line)) await api.updateHolding(line.id, { quantity: Number(draft.replace(/,/g, "")) });
      else await api.updateHolding(line.id, { value: draft });
      setEditing(null);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function remove(id: number) {
    setError(null);
    try {
      await api.removeHolding(id);
      setConfirming(null);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="table-wrap">
      {error && <p className="message error">{error}</p>}
      <table>
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
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => {
            const meta = assetMeta(line.asset_type);
            return (
              <tr key={line.id}>
                <td>
                  <div className="holding-name">
                    {/* On narrow screens the Type column is hidden; this dot keeps the type visible. */}
                    <span className="swatch show-narrow" title={meta.label} style={{ background: seriesVar(meta.slot) }} />
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
                <td className="right num">
                  {editing === line.id && priced(line) ? (
                    <input autoFocus onFocus={(e) => e.target.select()} value={draft} onChange={(e) => setDraft(e.target.value)} style={{ width: 110 }} aria-label="New quantity" />
                  ) : priced(line) ? (
                    quantity(line.quantity)
                  ) : (
                    ""
                  )}
                </td>
                <td className="right num hide-narrow">
                  {line.unit_price !== null ? `$${line.unit_price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : ""}
                </td>
                <td className="right num">
                  {editing === line.id && !priced(line) ? (
                    <input autoFocus onFocus={(e) => e.target.select()} value={draft} onChange={(e) => setDraft(e.target.value)} style={{ width: 120 }} aria-label="New value" />
                  ) : line.value_cents !== null ? (
                    money(line.value_cents)
                  ) : (
                    <span className="subtle">n/a</span>
                  )}
                </td>
                <td>
                  <div className="row-actions">
                    {editing === line.id ? (
                      <>
                        <button className="btn btn-small btn-primary" onClick={() => save(line)}>Save</button>
                        <button className="btn btn-small" onClick={() => setEditing(null)}>Cancel</button>
                      </>
                    ) : confirming === line.id ? (
                      <>
                        <button className="btn btn-small btn-danger" onClick={() => remove(line.id)}>Remove</button>
                        <button className="btn btn-small" onClick={() => setConfirming(null)}>Cancel</button>
                      </>
                    ) : (
                      <>
                        <button
                          className="btn btn-small"
                          aria-label={priced(line) ? `Edit amount of ${line.name}` : `Update value of ${line.name}`}
                          onClick={() => {
                            setEditing(line.id);
                            setConfirming(null);
                            setDraft(priced(line) ? String(line.quantity) : ((line.manual_value_cents ?? 0) / 100).toFixed(2));
                          }}
                        >
                          Edit
                        </button>
                        <button className="btn btn-small" onClick={() => { setConfirming(line.id); setEditing(null); }} aria-label={`Remove ${line.name}`}>
                          <span className="hide-narrow">Remove</span>
                          <span className="show-narrow" aria-hidden="true">✕</span>
                        </button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
