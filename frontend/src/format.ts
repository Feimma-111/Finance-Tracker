// Display helpers. Amounts arrive from the API as integer cents.

import type { AssetType } from "./api";

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const usdCompact = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 1,
});

export const money = (cents: number) => usd.format(cents / 100);
export const moneyAxis = (cents: number) => usdCompact.format(cents / 100);
export const signedMoney = (cents: number) => (cents > 0 ? "+" : "") + money(cents);

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
