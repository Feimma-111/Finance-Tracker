import { useState, type FormEvent } from "react";
import { api, type Cap } from "../api";
import { currencySymbol, displayCurrency, displayRate, money, monthLabel } from "../format";
import { useAsync } from "../hooks";
import { CategoryIcon } from "../icons";
import { Sheet } from "./Sheet";

/* Monthly spending caps. Each capped category gets a bar of how much of its cap
   is spent, with a marker for how much of the month has gone, and a status
   that says it in words too (never color alone): on track, close (90%+), over.
   Close or over caps offer "Why?", which runs the AI on just that category. */

const STATUS = {
  ok: { icon: "✓", label: "On track" },
  near: { icon: "!", label: "Close to the cap" },
  over: { icon: "▲", label: "Over" },
} as const;

export function CapsCard({
  month,
  version,
  categories,
  onChanged,
  onWhy,
}: {
  month: string;
  version: number;
  categories: string[]; // every spending category, for the editor
  onChanged: () => void;
  onWhy: (category: string) => void;
}) {
  const caps = useAsync(() => api.caps(month), [month, version]);
  const [editing, setEditing] = useState(false);
  const data = caps.data;
  const monthGone = data ? Math.round(data.month_share * 100) : 0;

  return (
    <section className={`card ${caps.loading && data ? "refreshing" : ""}`} style={{ marginTop: 16 }}>
      <div className="card-head">
        <h2 className="card-title">Category caps</h2>
        {data && data.caps.length > 0 && (
          <span className="card-subtitle">
            {monthLabel(month)}{data.month_share > 0 && data.month_share < 1 ? ` · ${monthGone}% of the month gone` : ""}
          </span>
        )}
        <button className="btn btn-small card-action" type="button" onClick={() => setEditing(true)}>
          {data?.caps.length ? "Edit caps" : "Set caps"}
        </button>
      </div>
      {caps.error && <p className="message error">{caps.error}</p>}
      {data && !data.caps.length && (
        <p className="hint" style={{ margin: 0 }}>
          Give any category a monthly limit, like $300 for Food. You'll see how close you are, and if one goes over,
          the AI can look at what pushed it there.
        </p>
      )}
      {data && data.caps.length > 0 && (
        <ul className="cap-list">
          {data.caps.map((cap) => (
            <CapRow key={cap.category} cap={cap} monthShare={data.month_share} onWhy={() => onWhy(cap.category)} />
          ))}
        </ul>
      )}
      {editing && (
        <CapEditor
          caps={data?.caps ?? []}
          categories={categories}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            onChanged();
          }}
        />
      )}
    </section>
  );
}

function CapRow({ cap, monthShare, onWhy }: { cap: Cap; monthShare: number; onWhy: () => void }) {
  const status = STATUS[cap.status];
  const fill = Math.min(cap.share, 1) * 100;
  return (
    <li className={`cap cap-${cap.status}`}>
      <CategoryIcon category={cap.category} size={32} />
      <div className="cap-main">
        <div className="cap-top">
          <strong>{cap.category}</strong>
          <span className="num">
            {money(cap.spent_cents)} <span className="subtle">of {money(cap.cap_cents)}</span>
          </span>
        </div>
        <div
          className="cap-track"
          role="meter"
          aria-valuemin={0}
          aria-valuemax={cap.cap_cents}
          aria-valuenow={cap.spent_cents}
          aria-label={`${cap.category}: ${Math.round(cap.share * 100)}% of the cap`}
        >
          <span className="cap-fill" style={{ width: `${fill}%` }} />
          {monthShare > 0 && monthShare < 1 && (
            <span className="cap-pace" style={{ left: `${monthShare * 100}%` }} title="How much of the month has gone" />
          )}
        </div>
        <div className="cap-bottom">
          <span className="cap-status">
            <span aria-hidden="true">{status.icon}</span>{" "}
            {cap.status === "over" ? `Over by ${money(-cap.left_cents)}` : `${status.label} · ${money(cap.left_cents)} left`}
          </span>
          {cap.status !== "ok" && (
            <button type="button" className="btn-link" onClick={onWhy}>Why?</button>
          )}
        </div>
      </div>
    </li>
  );
}

/** Caps for every category, in the display currency. Blank = no cap. */
function CapEditor({
  caps,
  categories,
  onClose,
  onSaved,
}: {
  caps: Cap[];
  categories: string[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const currency = displayCurrency();
  const start = (name: string) => {
    const cap = caps.find((c) => c.category === name);
    if (!cap) return "";
    // Shown in the display currency: exactly as set if it was set in it, else converted.
    const cents = cap.set_currency === currency ? cap.set_cents : Math.round(cap.cap_cents * displayRate());
    return (cents / 100).toFixed(currency === "TWD" || currency === "JPY" || currency === "KRW" ? 0 : 2);
  };
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(categories.map((c) => [c, start(c)])));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    // Only send what changed, so caps set in another currency stay exactly as they were.
    const changed = categories
      .filter((c) => values[c].trim() !== start(c))
      .map((c) => ({ category: c, amount: values[c].trim() || null }));
    try {
      if (changed.length) await api.saveCaps(changed, currency);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <Sheet title="Category caps" onClose={onClose}>
      <form className="form" onSubmit={save}>
        <p className="hint" style={{ margin: 0 }}>
          A monthly limit for each category, in {currency}. Leave one blank for no cap.
        </p>
        <div className="cap-editor">
          {categories.map((name) => (
            <label key={name} className="cap-edit-row">
              <CategoryIcon category={name} size={28} />
              <span>{name}</span>
              <div className="money-input">
                <i>{currencySymbol(currency)}</i>
                <input
                  type="text"
                  inputMode="decimal"
                  value={values[name]}
                  placeholder="no cap"
                  onChange={(e) => setValues((v) => ({ ...v, [name]: e.target.value }))}
                  aria-label={`Monthly cap for ${name}`}
                />
              </div>
            </label>
          ))}
        </div>
        {error && <p className="message error" style={{ margin: 0 }}>{error}</p>}
        <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? "Saving…" : "Save caps"}</button>
      </form>
    </Sheet>
  );
}
