import { useEffect, useState, type FormEvent } from "react";
import { api, type AssetType, type Frequency, type Kind, type Quote } from "../api";
import { ASSET_TYPES, currencySymbol, dateLabel, FREQUENCIES, frequencyText, moneyIn, todayIso } from "../format";
import { useAsync } from "../hooks";
import { AccountField, lastAccount, rememberAccount, useCashAccounts } from "./AccountField";
import { DateInput } from "./DateInput";

const CURRENCY_CHOICES: [string, string][] = [
  ["USD", "US dollar ($)"], ["TWD", "New Taiwan dollar (NT$)"], ["CNY", "Chinese yuan (CN¥)"],
  ["HKD", "Hong Kong dollar (HK$)"], ["JPY", "Japanese yen (¥)"], ["KRW", "Korean won (₩)"],
  ["EUR", "Euro (€)"], ["GBP", "British pound (£)"], ["CAD", "Canadian dollar (CA$)"],
];

function oneYearFromToday(): string {
  const [y, m, d] = todayIso().split("-");
  return `${Number(y) + 1}-${m}-${d}`;
}

/* ------------------------------------------------------------------ add a transaction
   Validation happens on the server (the same rules as the terminal app);
   this form just shows the server's message if something's off. */

export function TransactionForm({ onSaved, version }: { onSaved: () => void; version: number }) {
  const [mode, setMode] = useState<Kind | "transfer">("expense");
  return (
    <div className="form">
      <div className="segmented" role="group" aria-label="Transaction type">
        {(["expense", "income", "transfer"] as const).map((k) => (
          <button key={k} type="button" aria-pressed={mode === k} onClick={() => setMode(k)}>
            {k === "expense" ? "Expense" : k === "income" ? "Income" : "Transfer"}
          </button>
        ))}
      </div>
      {mode === "transfer" ? (
        <TransferForm onSaved={onSaved} version={version} />
      ) : (
        <EntryForm kind={mode} onSaved={onSaved} version={version} />
      )}
    </div>
  );
}

function EntryForm({ kind, onSaved, version }: { kind: Kind; onSaved: () => void; version: number }) {
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState("");
  // The category you've used before for this description fills itself in;
  // once you type or pick one yourself, yours wins.
  const [picked, setPicked] = useState(false);
  const [suggested, setSuggested] = useState<{ count: number; match?: string } | null>(null);
  const chooseCategory = (value: string) => {
    setCategory(value);
    setPicked(true);
    setSuggested(null);
  };
  useEffect(() => {
    const text = description.trim();
    if (picked || text.length < 2) return;
    const timer = setTimeout(() => {
      api.suggestCategory(text, kind).then(
        (s) => {
          if (s.category) {
            setCategory(s.category);
            setSuggested({ count: s.count ?? 1, match: s.match });
          } else if (suggested) {
            setCategory(""); // it was only our guess; don't leave a wrong one behind
            setSuggested(null);
          }
        },
        () => {},
      );
    }, 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [description, kind, picked]);
  const [date, setDate] = useState(todayIso());
  const [repeat, setRepeat] = useState<Frequency | "">("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);
  const categories = useAsync(() => api.categories(kind), [kind, version]);
  const listId = `categories-${kind}`;
  // Which cash account: the last one used, but "not from my accounts" for
  // costs someone else covers (rent a family member pays) -- unless you pick one.
  const accounts = useCashAccounts(version);
  const settings = useAsync(api.settings, [version]);
  const [accountChoice, setAccountChoice] = useState<number | null | undefined>(undefined);
  const covered = (settings.data?.covered_categories ?? []).some(
    (c) => c.toLowerCase() === category.trim().toLowerCase(),
  );
  // Travel mode's account wins over the last one used.
  const travel = settings.data?.travel_account_id ?? null;
  const fallback = travel !== null && accounts.some((a) => a.id === travel) ? travel : lastAccount(accounts);
  const accountId = accountChoice !== undefined ? accountChoice : covered ? null : fallback;
  // The amount is typed in the account's currency.
  const currency = accounts.find((a) => a.id === accountId)?.currency ?? "USD";

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      if (repeat) {
        const rule = await api.addRecurring({
          kind, description, amount, category, frequency: repeat, start_on: date, account_id: accountId,
        });
        const added = rule.created ? `Added ${rule.created} so far. ` : "";
        setMessage({
          text: `Repeats ${frequencyText(rule.frequency)}. ${added}Next on ${dateLabel(rule.next_due)}.`,
          error: false,
        });
        setRepeat("");
        setDate(todayIso());
      } else {
        const saved = await api.addTransaction({ kind, description, amount, category, occurred_on: date, account_id: accountId });
        setMessage({ text: `Saved ${moneyIn(saved.paid_cents, saved.currency)} for ${saved.description}.`, error: false });
      }
      setDescription("");
      setAmount("");
      rememberAccount(accountId);
      setAccountChoice(undefined);
      setPicked(false); // the next description gets a fresh suggestion
      setSuggested(null);
      onSaved();
    } catch (error) {
      setMessage({ text: (error as Error).message, error: true });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form" onSubmit={submit}>
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
            <i>{currencySymbol(currency)}</i>
            <input type="text" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" required />
          </div>
        </label>
        <label className="field">
          <span>{repeat ? "First date" : "Date"}</span>
          <DateInput value={date} max={repeat ? oneYearFromToday() : todayIso()} onChange={setDate} />
        </label>
      </div>
      <label className="field">
        <span>Repeat</span>
        <select
          value={repeat}
          onChange={(e) => {
            const next = e.target.value as Frequency | "";
            setRepeat(next);
            // A one-off can't be in the future; snap back if switching off repeat.
            if (!next && date > todayIso()) setDate(todayIso());
          }}
        >
          <option value="">Doesn't repeat</option>
          {FREQUENCIES.map((f) => (
            <option key={f.value} value={f.value}>{f.label}</option>
          ))}
        </select>
        {repeat && (
          <span className="hint">
            Added automatically {frequencyText(repeat)} from the first date. If that date is in the past,
            the payments since then are filled in too.
          </span>
        )}
      </label>
      <label className="field">
        <span>Category</span>
        <input type="text" list={listId} value={category} onChange={(e) => chooseCategory(e.target.value)} placeholder="Pick or type a new one" required />
        {suggested && category && (
          <span className="hint suggested">
            ✨ Filled in from {suggested.count} past{" "}
            {suggested.match === "same" ? `“${description.trim()}”` : "similar"} transaction{suggested.count === 1 ? "" : "s"}
          </span>
        )}
        <datalist id={listId}>
          {categories.data?.map((c) => <option key={c} value={c} />)}
        </datalist>
      </label>
      {!!categories.data?.length && (
        <div className="chips" aria-label="Recent categories">
          {categories.data.slice(0, 8).map((c) => (
            <button key={c} type="button" className="chip" onClick={() => chooseCategory(c)}>
              {c}
            </button>
          ))}
        </div>
      )}
      <AccountField
        kind={kind}
        accounts={accounts}
        value={accountId}
        onChange={setAccountChoice}
        hint={
          accountChoice === undefined && covered
            ? "Someone else covers this category, so it doesn't come out of your accounts."
            : undefined
        }
      />
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? "Saving…" : repeat ? `Add recurring ${kind}` : `Add ${kind}`}
        </button>
        {message && <span className={`message ${message.error ? "error" : "success"}`}>{message.text}</span>}
      </div>
    </form>
  );
}

/* ------------------------------------------------------------------ transfer between your accounts
   Not spending or income: it only moves money between two balances. Between
   currencies, "received" is prefilled at today's rate by the server if left
   blank -- type what your bank actually gave you when you know it. */

function TransferForm({ onSaved, version }: { onSaved: () => void; version: number }) {
  const accounts = useCashAccounts(version);
  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number | null>(null);
  const [amount, setAmount] = useState("");
  const [received, setReceived] = useState("");
  const [date, setDate] = useState(todayIso());
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);

  if (accounts.length < 2) {
    return <p className="hint" style={{ margin: 0 }}>Add at least two cash accounts on the Holdings page to move money between them.</p>;
  }
  const source = accounts.find((a) => a.id === (from ?? accounts[0].id))!;
  const target = accounts.find((a) => a.id === (to ?? accounts.find((a) => a.id !== source.id)!.id))!;
  const converting = source.currency !== target.currency;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const saved = await api.addTransfer({
        from_account_id: source.id, to_account_id: target.id, amount,
        received: converting && received.trim() ? received : undefined, occurred_on: date, note,
      });
      setMessage({
        text: `Moved ${moneyIn(saved.from_cents, saved.from_currency)} to ${saved.to_name}` +
          (converting ? ` (${moneyIn(saved.to_cents, saved.to_currency)} received).` : "."),
        error: false,
      });
      setAmount("");
      setReceived("");
      setNote("");
      onSaved();
    } catch (error) {
      setMessage({ text: (error as Error).message, error: true });
    } finally {
      setBusy(false);
    }
  }

  const pick = (value: number, set: (id: number) => void) => (
    <select value={value} onChange={(e) => set(Number(e.target.value))}>
      {accounts.map((a) => (
        <option key={a.id} value={a.id}>{a.name}{a.currency !== "USD" ? ` (${a.currency})` : ""}</option>
      ))}
    </select>
  );

  return (
    <form className="form" onSubmit={submit}>
      <div className="field-row">
        <label className="field"><span>From</span>{pick(source.id, setFrom)}</label>
        <label className="field"><span>To</span>{pick(target.id, setTo)}</label>
      </div>
      <div className="field-row">
        <label className="field">
          <span>Amount sent</span>
          <div className="money-input">
            <i>{currencySymbol(source.currency)}</i>
            <input type="text" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" required />
          </div>
        </label>
        {converting ? (
          <label className="field">
            <span>Amount received</span>
            <div className="money-input">
              <i>{currencySymbol(target.currency)}</i>
              <input type="text" inputMode="decimal" value={received} onChange={(e) => setReceived(e.target.value)} placeholder="today's rate" />
            </div>
          </label>
        ) : (
          <label className="field">
            <span>Date</span>
            <DateInput value={date} onChange={setDate} />
          </label>
        )}
      </div>
      {converting && (
        <label className="field">
          <span>Date</span>
          <DateInput value={date} onChange={setDate} />
        </label>
      )}
      <label className="field">
        <span>Note (optional)</span>
        <input type="text" value={note} onChange={(e) => setNote(e.target.value)} placeholder={converting ? "e.g. Wise" : "e.g. to savings"} maxLength={200} />
      </label>
      <p className="hint" style={{ margin: 0 }}>
        Transfers move money between your own accounts. They change both balances but never count as spending or income.
      </p>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <button className="btn btn-primary" type="submit" disabled={busy || source.id === target.id}>
          {busy ? "Saving…" : "Move money"}
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
  const [currency, setCurrency] = useState("USD");
  const [boughtOn, setBoughtOn] = useState("");
  const [avgPrice, setAvgPrice] = useState("");
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
        currency: type === "cash" ? currency : undefined,
        bought_on: priced && boughtOn ? boughtOn : undefined,
        avg_price: priced && avgPrice.trim() ? avgPrice : undefined,
      });
      setMessage({ text: `Added ${saved.name}.`, error: false });
      setName("");
      setSymbol("");
      setQuantity("");
      setValue("");
      setBoughtOn("");
      setAvgPrice("");
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
            <span>{type === "cash" ? "Balance today" : "Current value"}</span>
            <div className="money-input">
              <i>{currencySymbol(type === "cash" ? currency : "USD")}</i>
              <input type="text" inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} placeholder="0.00" required />
            </div>
          </label>
        )}
      </div>
      {priced && (
        <div className="field-row">
          <label className="field">
            <span>Bought on (optional)</span>
            <DateInput value={boughtOn} onChange={setBoughtOn} />
          </label>
          <label className="field">
            <span>Price paid {type === "gold" ? "per oz" : type === "crypto" ? "per coin" : "per share"} (optional)</span>
            <div className="money-input">
              <i>$</i>
              <input type="text" inputMode="decimal" value={avgPrice} onChange={(e) => setAvgPrice(e.target.value)} placeholder="average" />
            </div>
          </label>
        </div>
      )}
      {priced && (
        <p className="hint" style={{ margin: 0 }}>
          With these, the app shows how much it's gained since you bought it, and over any period.
        </p>
      )}
      {type === "cash" && (
        <label className="field">
          <span>Currency</span>
          <select value={currency} onChange={(e) => setCurrency(e.target.value)}>
            {CURRENCY_CHOICES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
          </select>
        </label>
      )}
      {type === "cash" && (
        <p className="hint" style={{ margin: 0 }}>
          Enter what your bank shows today. Transactions you add from now on and mark as paid from (or into) this
          account keep the balance up to date.
        </p>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? "Adding…" : "Add holding"}
        </button>
        {message && <span className={`message ${message.error ? "error" : "success"}`}>{message.text}</span>}
      </div>
    </form>
  );
}
