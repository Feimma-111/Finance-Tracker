import { useState, type FormEvent } from "react";
import { api, type AssetType, type Kind, type Quote } from "../api";
import { ASSET_TYPES, money, todayIso } from "../format";
import { useAsync } from "../hooks";

/* ------------------------------------------------------------------ add a transaction
   Validation happens on the server (the same rules as the terminal app);
   this form just shows the server's message if something's off. */

export function TransactionForm({ onSaved, version }: { onSaved: () => void; version: number }) {
  const [kind, setKind] = useState<Kind>("expense");
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState("");
  const [date, setDate] = useState(todayIso());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);
  const categories = useAsync(() => api.categories(kind), [kind, version]);
  const listId = `categories-${kind}`;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const saved = await api.addTransaction({ kind, description, amount, category, occurred_on: date });
      setMessage({ text: `Saved ${money(saved.amount_cents)} for ${saved.description}.`, error: false });
      setDescription("");
      setAmount("");
      onSaved();
    } catch (error) {
      setMessage({ text: (error as Error).message, error: true });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      <div className="segmented" role="group" aria-label="Transaction type">
        {(["expense", "income"] as Kind[]).map((k) => (
          <button key={k} type="button" aria-pressed={kind === k} onClick={() => setKind(k)}>
            {k === "expense" ? "Expense" : "Income"}
          </button>
        ))}
      </div>
      <label className="field">
        <span>Description</span>
        <input
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder={kind === "expense" ? "e.g. Groceries at Safeway" : "e.g. Paycheck"}
          required
        />
      </label>
      <div className="field-row">
        <label className="field">
          <span>Amount</span>
          <div className="money-input">
            <i>$</i>
            <input type="text" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" required />
          </div>
        </label>
        <label className="field">
          <span>Date</span>
          <input type="date" value={date} max={todayIso()} onChange={(e) => setDate(e.target.value)} />
        </label>
      </div>
      <label className="field">
        <span>Category</span>
        <input type="text" list={listId} value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Pick or type a new one" required />
        <datalist id={listId}>
          {categories.data?.map((c) => <option key={c} value={c} />)}
        </datalist>
      </label>
      {!!categories.data?.length && (
        <div className="chips" aria-label="Recent categories">
          {categories.data.slice(0, 8).map((c) => (
            <button key={c} type="button" className="chip" onClick={() => setCategory(c)}>
              {c}
            </button>
          ))}
        </div>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? "Saving…" : `Add ${kind}`}
        </button>
        {message && <span className={`message ${message.error ? "error" : "success"}`}>{message.text}</span>}
      </div>
    </form>
  );
}

/* ------------------------------------------------------------------ add a holding */

export function HoldingForm({ onSaved }: { onSaved: () => void }) {
  const [type, setType] = useState<AssetType>("cash");
  const [name, setName] = useState("");
  const [symbol, setSymbol] = useState("");
  const [quantity, setQuantity] = useState("");
  const [value, setValue] = useState("");
  const [quote, setQuote] = useState<{ quote?: Quote; error?: string; symbol: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);

  const priced = type === "stock" || type === "crypto" || type === "gold";
  const needsSymbol = type === "stock" || type === "crypto";
  const meta = ASSET_TYPES.find((a) => a.type === type)!;

  async function checkSymbol() {
    const s = symbol.trim().toUpperCase();
    if (!s || quote?.symbol === s) return;
    setQuote({ symbol: s });
    try {
      setQuote({ symbol: s, quote: await api.quote(s) });
    } catch (error) {
      setQuote({ symbol: s, error: (error as Error).message });
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const qty = Number(quantity.replace(/,/g, ""));
      const saved = await api.addHolding({
        asset_type: type,
        name: name || undefined,
        symbol: needsSymbol ? symbol : undefined,
        quantity: priced ? qty : undefined,
        value: priced ? undefined : value,
      });
      setMessage({ text: `Added ${saved.name}.`, error: false });
      setName("");
      setSymbol("");
      setQuantity("");
      setValue("");
      setQuote(null);
      onSaved();
    } catch (error) {
      setMessage({ text: (error as Error).message, error: true });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      <div className="segmented" role="group" aria-label="Asset type">
        {ASSET_TYPES.map((a) => (
          <button
            key={a.type}
            type="button"
            aria-pressed={type === a.type}
            onClick={() => {
              setType(a.type);
              setMessage(null);
            }}
          >
            {a.label}
          </button>
        ))}
      </div>
      <p className="hint" style={{ margin: 0 }}>{meta.hint}</p>

      {needsSymbol && (
        <label className="field">
          <span>Symbol</span>
          <input
            type="text"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            onBlur={checkSymbol}
            placeholder={type === "crypto" ? "BTC-USD" : "AAPL"}
            autoCapitalize="characters"
            required
          />
          {quote && (
            <span className={`message ${quote.error ? "error" : ""}`}>
              {quote.error
                ? quote.error
                : quote.quote
                  ? `${quote.quote.symbol} is at ${quote.quote.price.toLocaleString("en-US", { maximumFractionDigits: 2 })} ${quote.quote.currency}`
                  : "Looking up…"}
            </span>
          )}
        </label>
      )}

      <div className="field-row">
        {type !== "gold" && (
          <label className="field">
            <span>{priced ? "Name (optional)" : "Name"}</span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={type === "cash" ? "Checking" : type === "other" ? "Car" : symbol.toUpperCase() || "Apple"}
              required={!priced}
            />
          </label>
        )}
        {priced ? (
          <label className="field">
            <span>{type === "gold" ? "Troy ounces" : type === "crypto" ? "Amount owned" : "Shares"}</span>
            <input type="text" inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} placeholder="0" required />
          </label>
        ) : (
          <label className="field">
            <span>Current value</span>
            <div className="money-input">
              <i>$</i>
              <input type="text" inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} placeholder="0.00" required />
            </div>
          </label>
        )}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? "Adding…" : "Add holding"}
        </button>
        {message && <span className={`message ${message.error ? "error" : "success"}`}>{message.text}</span>}
      </div>
    </form>
  );
}
