// Typed wrappers around the Python REST API (finance_tracker/api.py).
// Every screen talks to the backend through this file only.

export type Kind = "expense" | "income";
export type AssetType = "cash" | "stock" | "crypto" | "gold" | "other";

export interface Transaction {
  id: number;
  description: string;
  amount_cents: number;
  category: string;
  occurred_on: string; // YYYY-MM-DD
  kind: Kind;
  recurring_id: number | null; // set when a recurring rule created it
  account_id: number | null; // the cash account it came out of / went into
  currency: string; // what it was paid in (its account's currency); amount_cents is always USD
  paid_cents: number; // the amount in that currency
}

export type Frequency = "weekly" | "biweekly" | "monthly" | "yearly";

export interface RecurringRule {
  id: number;
  description: string;
  amount_cents: number;
  category: string;
  kind: Kind;
  frequency: Frequency;
  start_on: string;
  next_due: string;
  active: boolean;
  account_id: number | null;
  currency: string; // amount_cents is in this currency
}

export interface Settings {
  theme: "system" | "light" | "dark";
  database: string;
  ai_url: string; // "" = AI analyst not set up
  ai_model: string;
  covered_categories: string[]; // expenses someone else pays for (e.g. a family member pays rent)
  covered_note: string;
  display_currency: string; // amounts are shown in this (USD by default)
  travel_account_id: number | null; // travel mode: new transactions default to this account
  currencies: { code: string; symbol: string; decimals: number }[];
  income: Income;
}

/** Your pay, for the savings check. monthly_cents is take-home, in ``currency``. */
export interface Income {
  hourly_cents: number | null;
  currency: string;
  hours_per_week: number | null;
  tax_pct: number;
  monthly_cents: number | null;
}

/** A savings goal. Amounts are USD cents unless they say "set" (as entered, in ``currency``). */
export interface Goal {
  id: number;
  name: string;
  currency: string;
  target_set_cents: number;
  saved_set_cents: number;
  target_date: string | null;
  account_id: number | null; // progress = this account's balance
  account_name: string | null;
  target_cents: number | null;
  saved_cents: number | null;
  left_cents: number | null;
  share: number | null;
  per_month_cents: number | null; // to reach it by its date
  months_left: number | null;
}
export interface GoalInput {
  name: string;
  target: string;
  currency: string;
  target_date?: string;
  account_id?: number | null;
  saved?: string;
}
export interface SavingsCheck {
  created_at: string;
  model: string;
  review: { headline: string; can_save: string[]; goals: string[]; ideas: string[] };
  facts: string;
}

export interface AiStatus {
  configured: boolean;
  reachable: boolean;
  url: string;
  models: string[];
  model: string | null; // the model reviews will use
  error?: string;
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface AskResult {
  answer: string;
  model: string;
  steps: { tool: string; arguments: Record<string, unknown>; result: Record<string, unknown> }[];
  unverified: string[]; // numbers in the answer that no tool returned
}

export interface ImportMapping {
  date: string | null;
  description: string | null;
  amount: string | null; // one signed column...
  debit: string | null; // ...or separate money-out / money-in columns
  credit: string | null;
  category: string | null;
  kind: string | null;
}

export interface ImportOptions {
  date_format: string; // "auto" or e.g. "MM/DD/YYYY"
  positive_is: "income" | "expense";
  default_category: string;
}

export interface ImportPreview {
  headers: string[];
  mapping: ImportMapping;
  total_rows: number;
  date_format_choices: string[];
  date_formats: string[]; // the formats that fit this file
  problem: string | null; // set when the mapping can't work yet
  date_format?: string;
  ready?: number;
  duplicates?: number;
  error_count?: number;
  errors?: string[];
  sample?: { line: number; date: string; description: string; category: string; amount_cents: number; kind: Kind }[];
}

export interface ImportResult {
  imported: number;
  duplicates: number;
  error_count: number;
  errors: string[];
}

export interface ReviewText {
  headline: string;
  observations: string[];
  suggestions: string[];
}

/** What a follow-up question is about: the server uses that analysis's facts as context. */
export type AskAbout = { focus?: { month: string; categories: string[] }; review_month?: string; savings?: boolean };

export interface SavedReview {
  month: string;
  created_at: string; // ISO timestamp, UTC
  model: string;
  review: ReviewText;
  facts: string; // exactly what the model was shown
  outdated?: boolean; // data or covered expenses changed after it was written
}

/** The AI's look at only the chosen categories (kept for the browser session, not saved). */
export interface FocusResult {
  month: string;
  categories: string[];
  created_at: string; // ISO timestamp, UTC
  model: string;
  review: ReviewText;
  facts: string;
}

export interface Summary {
  month: string;
  current_month: string;
  spent_cents: number;
  income_cents: number;
  net_cents: number;
  transaction_count: number;
}

export interface CategoryReport {
  month: string | null;
  total_cents: number;
  items: { category: string; total_cents: number; share: number }[];
}

/** One category's spending, grouped by what was bought ("Boba ×3"). */
export interface PurchaseReport {
  month: string | null;
  category: string;
  total_cents: number;
  count: number; // purchases in all
  items: { description: string; count: number; total_cents: number; share: number }[];
}

export interface MonthRow {
  month: string;
  total_cents: number;
  z_score: number | null;
  label: string;
  in_progress: boolean;
}

export interface MonthlyReport {
  mean_cents: number | null;
  stdev_cents: number | null;
  months: MonthRow[];
}

export interface Pace {
  month: string;
  previous_month: string;
  days_in_month: number;
  through_day: number; // last day included (today, for the current month)
  in_progress: boolean;
  controlled: boolean; // covered categories left out
  covered_categories: string[];
  categories: string[] | null; // only these categories (null = all)
  this_month: { day: number; cumulative_cents: number }[];
  last_month: { day: number; cumulative_cents: number }[];
  spent_cents: number;
  last_month_same_point_cents: number;
  last_month_total_cents: number;
  difference_cents: number;
}

export interface Holding {
  id: number;
  asset_type: AssetType;
  name: string;
  symbol: string | null;
  quantity: number;
  manual_value_cents: number | null;
  bought_on: string | null; // investments: first bought
  cost_basis_cents: number | null; // investments: total paid for the quantity held
  balance_as_of: string | null; // cash: the day the balance was checked
  currency: string; // cash: the balance's currency
}

export interface NetWorthLine extends Holding {
  value_cents: number | null;
  unit_price: number | null;
  note: string;
  balance_cents: number | null; // cash: the balance now, in the account's currency (value_cents is USD)
  balance_change_cents: number; // cash: moved by linked transactions and transfers since balance_as_of
}

/** One line under a holding's dropdown. Amounts are in the holding's currency, signed. */
export interface ActivityItem {
  type: "expense" | "income" | "transfer" | "bought";
  id: number;
  date: string | null;
  description: string;
  category: string | null; // a transfer's note
  amount_cents: number | null;
  quantity?: number;
  counted: boolean; // false: already part of the balance you entered
}
export interface HoldingActivity {
  holding: Holding;
  items: ActivityItem[];
  balance: { date: string; amount_cents: number | null } | null; // when the balance was last entered
}

/** A monthly spending cap on one category. Amounts are USD cents unless noted. */
export interface Cap {
  category: string;
  cap_cents: number;
  spent_cents: number;
  left_cents: number; // negative when over
  share: number; // spent / cap
  status: "ok" | "near" | "over";
  set_cents: number; // the cap as you set it...
  set_currency: string; // ...in this currency
}
export interface Caps {
  month: string;
  month_share: number; // how much of the month has gone, 0-1
  caps: Cap[];
}

/** Money moved between two of your own accounts (not spending or income). */
export interface TransferItem {
  id: number;
  occurred_on: string;
  from_account_id: number;
  from_name: string;
  from_currency: string;
  from_cents: number;
  to_account_id: number;
  to_name: string;
  to_currency: string;
  to_cents: number;
  note: string;
}

export interface NetWorth {
  total_cents: number;
  liquid_cents: number; // every cash account together
  complete: boolean;
  change_cents: number | null;
  change_since: string | null;
  by_type: { asset_type: AssetType; value_cents: number }[];
  lines: NetWorthLine[];
}

export interface Snapshot {
  date: string;
  total_cents: number;
}

export interface Quote {
  symbol: string;
  price: number;
  currency: string;
  fetched_at: string;
  stale: boolean;
}

export interface NewTransaction {
  description: string;
  amount: string;
  category: string;
  occurred_on: string;
  kind: Kind;
  account_id?: number | null;
}

export interface NewHolding {
  asset_type: AssetType;
  name?: string;
  symbol?: string;
  quantity?: number;
  value?: string;
  bought_on?: string;
  avg_price?: string; // price paid per share / unit
  currency?: string; // cash accounts
}

export type Period = "1W" | "1M" | "3M" | "YTD" | "1Y" | "ALL";
export interface Change {
  change_cents: number;
  pct: number | null;
}
export interface PortfolioHolding extends Holding {
  value_cents: number | null;
  unit_price?: number | null;
  avg_price?: number | null;
  total?: Change | null; // since buying (needs what you paid)
  period?: Change | null;
  today?: Change | null;
  note: string;
}
export interface Portfolio {
  period: Period;
  start: string;
  value_cents: number;
  cost_cents: number | null;
  total: Change | null;
  period_change: Change | null;
  today: Change | null;
  holdings: PortfolioHolding[];
  series: { date: string; value_cents: number }[];
}

/** The AI's look at your investments and the market (kept for the browser session). */
export interface HoldingsReview {
  created_at: string;
  model: string;
  review: { headline: string; holdings: string[]; market: string[]; keep_in_mind: string[] };
  facts: string;
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export const LOCKED_EVENT = "finance-tracker:locked";

export interface AuthStatus {
  passcode_set: boolean;
  signed_in: boolean;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new Error("Can't reach the server. Is `python main.py --web` running?");
  }
  if (response.status === 401 && !path.startsWith("/api/auth/")) {
    // Signed out (session expired, or locked from another tab): show the lock screen.
    window.dispatchEvent(new Event(LOCKED_EVENT));
  }
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      message = describeDetail((await response.json()).detail) ?? message;
    } catch {
      // body wasn't JSON; keep the status text
    }
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

// FastAPI sends either a string, or (for malformed requests) a list of field errors.
function describeDetail(detail: unknown): string | undefined {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => `${d.loc?.[d.loc.length - 1] ?? "field"}: ${d.msg}`)
      .join("; ");
  }
  return undefined;
}

function query(params: Record<string, string | undefined | null>): string {
  const entries = Object.entries(params).filter(([, v]) => v) as [string, string][];
  return entries.length ? `?${new URLSearchParams(entries)}` : "";
}

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });

export const api = {
  authStatus: () => request<AuthStatus>("/api/auth/status"),
  setupPasscode: (passcode: string) => request<AuthStatus>("/api/auth/setup", json("POST", { passcode })),
  login: (passcode: string) => request<AuthStatus>("/api/auth/login", json("POST", { passcode })),
  logout: () => request<{ signed_in: boolean }>("/api/auth/logout", { method: "POST" }),
  changePasscode: (current: string, next: string) =>
    request<{ changed: boolean; signed_out_devices: number }>("/api/auth/change", json("POST", { current, new: next })),

  profile: () => request<{ name: string | null }>("/api/profile"),
  createProfile: (name: string) => request<{ name: string }>("/api/profile", json("POST", { name })),
  renameProfile: (name: string) => request<{ name: string }>("/api/profile", json("PUT", { name })),

  settings: () => request<Settings>("/api/settings"),
  saveSettings: (
    body: Partial<Pick<Settings,
      "theme" | "ai_url" | "ai_model" | "covered_categories" | "covered_note" | "display_currency" | "travel_account_id">> & {
      income_hourly?: string; income_currency?: string; income_hours_per_week?: number; income_tax_pct?: number;
    },
  ) =>
    request<Settings>("/api/settings", json("PUT", body)),

  importPreview: (csv: string, mapping?: ImportMapping, options?: ImportOptions) =>
    request<ImportPreview>("/api/import/preview", json("POST", { csv, mapping, options })),
  importCsv: (csv: string, mapping: ImportMapping, options: ImportOptions) =>
    request<ImportResult>("/api/import", json("POST", { csv, mapping, options })),

  aiStatus: () => request<AiStatus>("/api/ai/status"),
  savedReview: (month: string) => request<{ saved: SavedReview | null }>(`/api/ai/reviews/${month}`),
  createReview: (month: string) => request<SavedReview>(`/api/ai/reviews/${month}`, { method: "POST" }),
  focusReview: (month: string, categories: string[]) =>
    request<FocusResult>("/api/ai/focus", json("POST", { month, categories })),
  aiChanged: () => request<{ changed_at: string | null }>("/api/ai/changed"),
  ask: (question: string, history: ChatTurn[], about?: AskAbout) =>
    request<AskResult>("/api/ai/ask", json("POST", { question, history, ...about })),

  recurring: () => request<RecurringRule[]>("/api/recurring"),
  addRecurring: (body: Omit<NewTransaction, "occurred_on"> & { frequency: Frequency; start_on: string }) =>
    request<RecurringRule & { created: number }>("/api/recurring", json("POST", body)),
  updateRecurring: (id: number, body: { active?: boolean; amount?: string }) =>
    request<RecurringRule>(`/api/recurring/${id}`, json("PATCH", body)),
  deleteRecurring: (id: number) => request<void>(`/api/recurring/${id}`, { method: "DELETE" }),

  summary: (month?: string | null) => request<Summary>(`/api/summary${query({ month })}`),
  months: () => request<string[]>("/api/months"),
  categories: (kind: Kind) => request<string[]>(`/api/categories${query({ kind })}`),

  transactions: (month?: string | null) =>
    request<{ items: Transaction[]; total: number }>(`/api/transactions${query({ month, limit: "5000" })}`),
  addTransaction: (body: NewTransaction) => request<Transaction>("/api/transactions", json("POST", body)),
  getTransaction: (id: number) => request<Transaction & { matching: number }>(`/api/transactions/${id}`),
  updateTransaction: (id: number, body: Partial<NewTransaction> & { apply_category_to_matching?: boolean }) =>
    request<Transaction & { also_updated: number }>(`/api/transactions/${id}`, json("PATCH", body)),
  deleteTransaction: (id: number) => request<void>(`/api/transactions/${id}`, { method: "DELETE" }),
  makeRecurring: (id: number, frequency: Frequency, fillMissing: boolean) =>
    request<RecurringRule & { linked: number; created: number }>(
      `/api/transactions/${id}/recurring`, json("POST", { frequency, fill_missing: fillMissing })),

  backups: () => request<Backups>("/api/backups"),
  backupNow: () => request<Backups & { name: string | null }>("/api/backups", { method: "POST" }),

  categoryReport: (month?: string | null) => request<CategoryReport>(`/api/reports/categories${query({ month })}`),
  purchases: (category: string, month?: string | null) =>
    request<PurchaseReport>(`/api/reports/purchases${query({ category, month })}`),
  monthlyReport: () => request<MonthlyReport>("/api/reports/monthly"),
  pace: (month: string, categories?: string[]) => {
    const params = new URLSearchParams({ month });
    categories?.forEach((c) => params.append("category", c));
    return request<Pace>(`/api/reports/pace?${params}`);
  },

  holdings: () => request<Holding[]>("/api/holdings"),
  holdingActivity: (id: number) => request<HoldingActivity>(`/api/holdings/${id}/activity`),
  addHolding: (body: NewHolding) => request<Holding>("/api/holdings", json("POST", body)),
  updateHolding: (
    id: number,
    body: { quantity?: number; value?: string; name?: string; symbol?: string; bought_on?: string; avg_price?: string },
  ) =>
    request<Holding>(`/api/holdings/${id}`, json("PATCH", body)),
  removeHolding: (id: number) => request<void>(`/api/holdings/${id}`, { method: "DELETE" }),
  quote: (symbol: string) => request<Quote>(`/api/quotes/${encodeURIComponent(symbol)}`),

  netWorth: () => request<NetWorth>("/api/net-worth"),
  portfolio: (period: Period) => request<Portfolio>(`/api/portfolio${query({ period })}`),
  holdingsReview: () => request<HoldingsReview>("/api/ai/holdings", { method: "POST" }),
  fx: (currency: string) => request<{ currency: string; rate: number }>(`/api/fx${query({ currency })}`),
  caps: (month: string) => request<Caps>(`/api/caps${query({ month })}`),
  suggestCategory: (description: string, kind: Kind) =>
    request<{ category: string | null; count?: number; match?: "same" | "similar" }>(
      `/api/categories/suggest${query({ description, kind })}`),
  goals: () => request<Goal[]>("/api/goals"),
  addGoal: (body: GoalInput) => request<Goal>("/api/goals", json("POST", body)),
  updateGoal: (id: number, body: GoalInput) => request<Goal>(`/api/goals/${id}`, json("PUT", body)),
  deleteGoal: (id: number) => request<void>(`/api/goals/${id}`, { method: "DELETE" }),
  savingsCheck: () => request<SavingsCheck>("/api/ai/savings", { method: "POST" }),
  saveCaps: (caps: { category: string; amount: string | null }[], currency: string) =>
    request<Caps>("/api/caps", json("PUT", { caps, currency })),
  transfers: () => request<TransferItem[]>("/api/transfers"),
  addTransfer: (body: {
    from_account_id: number; to_account_id: number; amount: string; received?: string; occurred_on: string; note?: string;
  }) => request<TransferItem>("/api/transfers", json("POST", body)),
  deleteTransfer: (id: number) => request<void>(`/api/transfers/${id}`, { method: "DELETE" }),
  netWorthHistory: () => request<Snapshot[]>("/api/net-worth/history"),
};

export const CSV_EXPORT_URL = "/api/transactions.csv";
export const BACKUP_DOWNLOAD_URL = "/api/backups/download";

export interface Backups {
  location: string;
  backups: { name: string; size: number; created: string }[];
}
