// Icons: an emoji per category (picked by keywords in the category or
// description) on a round badge in one of Google Calendar's event colors, plus
// the small line icons used in the phone tab bar. Every category gets a color:
// known ones a fitting one, others one picked from the name, so it's stable.

import type { AssetType } from "./api";

type Tint = "orange" | "green" | "blue" | "purple" | "pink" | "teal" | "yellow" | "red" | "indigo" | "lavender" | "gray";
const NAME_TINTS: Tint[] = ["blue", "orange", "green", "purple", "pink", "teal", "yellow", "red", "indigo", "lavender"];

// First match wins, so more specific words come first.
const RULES: { words: string[]; emoji: string; tint: Tint }[] = [
  { words: ["tuition", "school", "college", "university", "textbook", "education", "class"], emoji: "🎓", tint: "indigo" },
  { words: ["rent", "housing", "mortgage", "apartment", "home"], emoji: "🏠", tint: "blue" },
  { words: ["grocer", "supermarket", "safeway", "trader joe", "whole foods", "costco"], emoji: "🛒", tint: "green" },
  { words: ["coffee", "cafe", "starbucks", "boba", "tea"], emoji: "☕", tint: "orange" },
  { words: ["food", "dining", "restaurant", "eating", "lunch", "dinner", "breakfast", "takeout"], emoji: "🍔", tint: "orange" },
  { words: ["salary", "paycheck", "payroll", "income", "wage", "deposit"], emoji: "💵", tint: "green" },
  { words: ["subscription", "streaming", "netflix", "spotify", "hulu", "youtube", "disney"], emoji: "📺", tint: "red" },
  { words: ["travel", "holiday", "vacation", "flight", "hotel", "airbnb", "trip"], emoji: "✈️", tint: "teal" },
  { words: ["gas", "fuel", "shell", "chevron"], emoji: "⛽", tint: "yellow" },
  { words: ["transport", "transit", "uber", "lyft", "bus", "rail", "train", "parking", "car"], emoji: "🚌", tint: "yellow" },
  { words: ["phone", "mobile", "cell", "t-mobile", "verizon"], emoji: "📱", tint: "indigo" },
  { words: ["utilit", "electric", "water", "internet", "wifi", "power"], emoji: "💡", tint: "yellow" },
  { words: ["insurance"], emoji: "🛡️", tint: "blue" },
  { words: ["gym", "fitness", "sport"], emoji: "🏋️", tint: "purple" },
  { words: ["health", "medical", "pharmacy", "doctor", "dental"], emoji: "💊", tint: "pink" },
  { words: ["entertainment", "movie", "cinema", "game", "concert", "fun", "music"], emoji: "🎬", tint: "purple" },
  { words: ["gift", "donation", "charity"], emoji: "🎁", tint: "pink" },
  { words: ["pet", "vet"], emoji: "🐾", tint: "orange" },
  { words: ["bank", "fee", "interest", "atm"], emoji: "🏦", tint: "gray" },
  { words: ["shopping", "amazon", "clothes", "clothing", "lifestyle", "want"], emoji: "🛍️", tint: "pink" },
  { words: ["need", "household", "supplies"], emoji: "🧾", tint: "teal" },
  { words: ["saving", "invest"], emoji: "📈", tint: "green" },
];

function match(text: string) {
  const low = text.toLowerCase();
  return RULES.find((rule) => rule.words.some((w) => low.includes(w)));
}

/** A category's color tint: from its keywords, else picked from its name (always the same). */
function categoryTint(category: string, hint?: string): Tint {
  const found = match(category) ?? (hint ? match(hint) : undefined);
  if (found) return found.tint;
  let hash = 0;
  for (const ch of category.trim().toLowerCase()) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return NAME_TINTS[hash % NAME_TINTS.length];
}

/** The category's color as a CSS value, e.g. for its checkbox in the category picker. */
export const categoryColor = (category: string) => `var(--tint-${categoryTint(category)})`;

/** A category's icon. ``hint`` (e.g. the description) is tried if the category has no match. */
export function CategoryIcon({ category, hint, size = 36 }: { category: string; hint?: string; size?: number }) {
  const found = match(category) ?? (hint ? match(hint) : undefined);
  const letter = category.trim().charAt(0).toUpperCase() || "•";
  return (
    <span
      className={`icon-tile tint-${categoryTint(category, hint)}`}
      style={{ width: size, height: size, fontSize: found ? size * 0.5 : size * 0.42 }}
      aria-hidden="true"
    >
      {found ? found.emoji : letter}
    </span>
  );
}

const ASSET_ICONS: Record<AssetType, { emoji: string; tint: Tint }> = {
  cash: { emoji: "🏦", tint: "blue" },
  stock: { emoji: "📈", tint: "orange" },
  crypto: { emoji: "🪙", tint: "teal" },
  gold: { emoji: "🥇", tint: "yellow" },
  other: { emoji: "📦", tint: "pink" },
};

export function AssetIcon({ type, size = 36 }: { type: AssetType; size?: number }) {
  const icon = ASSET_ICONS[type];
  return (
    <span className={`icon-tile tint-${icon.tint}`} style={{ width: size, height: size, fontSize: size * 0.5 }} aria-hidden="true">
      {icon.emoji}
    </span>
  );
}

/* ------------------------------------------------------------------ tab bar icons (SF Symbols-like strokes) */

const stroke = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round" } as const;

export const TabIcons = {
  dashboard: (
    <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
      <path {...stroke} d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" />
    </svg>
  ),
  transactions: (
    <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
      <path {...stroke} d="M8 6h12M8 12h12M8 18h12" />
      <circle cx="4" cy="6" r="1.2" fill="currentColor" />
      <circle cx="4" cy="12" r="1.2" fill="currentColor" />
      <circle cx="4" cy="18" r="1.2" fill="currentColor" />
    </svg>
  ),
  holdings: (
    <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
      <path {...stroke} d="M3 20h18M6 16v-5M11 16V8M16 16v-3M20 16V5" />
    </svg>
  ),
  settings: (
    <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
      <circle {...stroke} cx="12" cy="12" r="3" />
      <path {...stroke} d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
    </svg>
  ),
  plus: (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
      <path {...stroke} strokeWidth={2.2} d="M12 5v14M5 12h14" />
    </svg>
  ),
  search: (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <circle {...stroke} cx="11" cy="11" r="7" />
      <path {...stroke} d="m20 20-3.5-3.5" />
    </svg>
  ),
};
