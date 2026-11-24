// Display helpers. Amounts arrive from the API as integer cents.

import type { AssetType, Frequency } from "./api";

export const FREQUENCIES: { value: Frequency; label: string; every: string }[] = [
  { value: "weekly", label: "Weekly", every: "every week" },
  { value: "biweekly", label: "Every 2 weeks", every: "every 2 weeks" },
  { value: "monthly", label: "Monthly", every: "every month" },
  { value: "yearly", label: "Yearly", every: "every year" },
];
export const frequencyText = (f: Frequency) => FREQUENCIES.find((x) => x.value === f)!.every;

/* Currencies. The API reports everything in US cents. ``money`` shows it in
   the display currency (Settings; USD by default) at today's rate, set once
   at startup by setDisplayCurrency. ``moneyIn`` shows an amount in its own
   currency with no conversion -- e.g. what you actually paid in NT$. */

const WHOLE = new Set(["TWD", "JPY", "KRW"]); // shown without decimals
const formats = new Map<string, Intl.NumberFormat>();

function formatter(currency: string, compact = false): Intl.NumberFormat {
  const key = `${currency}:${compact}`;
  let f = formats.get(key);
  if (!f) {
    const digits = WHOLE.has(currency) ? 0 : 2;
    f = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      ...(compact
        ? { notation: "compact", maximumFractionDigits: 1 }
        : { minimumFractionDigits: digits, maximumFractionDigits: digits }),
    });
    formats.set(key, f);
  }
  return f;
}

// Start with the last currency and rate this device used, so a reload doesn't
// flash US dollars before today's rate arrives (App then refreshes it).
const DISPLAY_KEY = "finance-tracker:display";
let display = { currency: "USD", rate: 1 };
try {
  const saved = JSON.parse(localStorage.getItem(DISPLAY_KEY) ?? "null");
  if (saved && typeof saved.currency === "string" && saved.rate > 0) display = saved;
} catch {
  // storage blocked: start in dollars
}

/** Show amounts in ``currency``, at ``rate`` units per US dollar. */
export function setDisplayCurrency(currency: string, rate: number): void {
  display = { currency, rate };
  try {
    localStorage.setItem(DISPLAY_KEY, JSON.stringify(display));
  } catch {
    // ignore
  }
}
export const displayCurrency = () => display.currency;
export const displayRate = () => display.rate;
/** Room for money labels on a chart's y-axis ("NT$65.6K" is wider than "$65.6K"). */
export const axisWidth = () => 50 + 7 * currencySymbol(display.currency).length;

export const money = (cents: number) => formatter(display.currency).format((cents * display.rate) / 100);
export const moneyAxis = (cents: number) => formatter(display.currency, true).format((cents * display.rate) / 100);
export const signedMoney = (cents: number) => (cents > 0 ? "+" : "") + money(cents);
/** An amount in its own currency (no conversion): 35000, "TWD" -> "NT$350". */
export const moneyIn = (cents: number, currency: string) => formatter(currency).format(cents / 100);
/** "$", "NT$" -- for the prefix inside amount fields. */
export const currencySymbol = (currency: string) =>
  formatter(currency).formatToParts(0).find((p) => p.type === "currency")?.value ?? currency;

export const quantity = (value: number) => value.toLocaleString("en-US", { maximumFractionDigits: 6 });
export const percent = (share: number) =>
  share > 0 && share < 0.001 ? "<0.1%" : `${(share * 100).toFixed(1)}%`;

// Parse YYYY-MM-DD as a *local* date. `new Date("2026-11-03")` would be read as
// UTC midnight and can show up as Nov 2 in US time zones.
function localDate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, (m ?? 1) - 1, d ?? 1);
}

export const dateLabel = (iso: string) =>
  localDate(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
export const dateShort = (iso: string) =>
  localDate(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
export const monthLabel = (month: string) =>
  localDate(`${month}-01`).toLocaleDateString("en-US", { month: "long", year: "numeric" });
export const monthShort = (month: string) =>
  localDate(`${month}-01`).toLocaleDateString("en-US", { month: "short" });

export function todayIso(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}
export const currentMonth = () => todayIso().slice(0, 7);

// Each asset type keeps the same color everywhere (color follows the entity).
// The order is the validated categorical order -- see styles.css.
export const ASSET_TYPES: { type: AssetType; label: string; hint: string; slot: number }[] = [
  { type: "cash", label: "Cash", hint: "Bank accounts, savings, cash on hand", slot: 1 },
  { type: "stock", label: "Stocks", hint: "Shares or ETFs by ticker, e.g. AAPL, VOO", slot: 2 },
  { type: "crypto", label: "Crypto", hint: "By Yahoo symbol, e.g. BTC-USD", slot: 3 },
  { type: "gold", label: "Gold", hint: "Troy ounces, priced live", slot: 4 },
  { type: "other", label: "Other", hint: "Anything you value by hand: car, collectibles", slot: 5 },
];

export const assetMeta = (type: AssetType) => ASSET_TYPES.find((a) => a.type === type)!;
export const seriesVar = (slot: number) => `var(--series-${slot})`;
