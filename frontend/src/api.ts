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

export interface Holding {
  id: number;
  asset_type: AssetType;
  name: string;
  symbol: string | null;
  quantity: number;
  manual_value_cents: number | null;
}

export interface NetWorthLine extends Holding {
  value_cents: number | null;
  unit_price: number | null;
  note: string;
}

export interface NetWorth {
  total_cents: number;
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
}

export interface NewHolding {
  asset_type: AssetType;
  name?: string;
  symbol?: string;
  quantity?: number;
  value?: string;
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
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
  profile: () => request<{ name: string | null }>("/api/profile"),
  createProfile: (name: string) => request<{ name: string }>("/api/profile", json("POST", { name })),

  summary: (month?: string | null) => request<Summary>(`/api/summary${query({ month })}`),
  months: () => request<string[]>("/api/months"),
  categories: (kind: Kind) => request<string[]>(`/api/categories${query({ kind })}`),

  transactions: (month?: string | null) =>
    request<{ items: Transaction[]; total: number }>(`/api/transactions${query({ month, limit: "5000" })}`),
  addTransaction: (body: NewTransaction) => request<Transaction>("/api/transactions", json("POST", body)),
  deleteTransaction: (id: number) => request<void>(`/api/transactions/${id}`, { method: "DELETE" }),

  categoryReport: (month?: string | null) => request<CategoryReport>(`/api/reports/categories${query({ month })}`),
  monthlyReport: () => request<MonthlyReport>("/api/reports/monthly"),

  holdings: () => request<Holding[]>("/api/holdings"),
  addHolding: (body: NewHolding) => request<Holding>("/api/holdings", json("POST", body)),
  updateHolding: (id: number, body: { quantity?: number; value?: string }) =>
    request<Holding>(`/api/holdings/${id}`, json("PATCH", body)),
  removeHolding: (id: number) => request<void>(`/api/holdings/${id}`, { method: "DELETE" }),
  quote: (symbol: string) => request<Quote>(`/api/quotes/${encodeURIComponent(symbol)}`),

  netWorth: () => request<NetWorth>("/api/net-worth"),
  netWorthHistory: () => request<Snapshot[]>("/api/net-worth/history"),
};

export const CSV_EXPORT_URL = "/api/transactions.csv";
