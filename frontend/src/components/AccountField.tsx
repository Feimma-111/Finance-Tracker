import { api, type Holding, type Kind } from "../api";
import { useAsync } from "../hooks";

/* Which cash account a transaction came out of (or went into). Linking one
   keeps that account's balance -- and your liquid total -- up to date. */

const LAST_KEY = "finance-tracker:last-account";

/** Your cash accounts (cash holdings), newest data on every change. */
export function useCashAccounts(version?: number): Holding[] {
  const list = useAsync(api.holdings, [version]);
  return (list.data ?? []).filter((h) => h.asset_type === "cash");
}

/** The account used last on this device, or the first one. */
export function lastAccount(accounts: Holding[]): number | null {
  try {
    const saved = Number(localStorage.getItem(LAST_KEY));
    if (accounts.some((a) => a.id === saved)) return saved;
  } catch {
    // storage blocked: fall back to the first account
  }
  return accounts[0]?.id ?? null;
}

export function rememberAccount(id: number | null): void {
  if (id === null) return;
  try {
    localStorage.setItem(LAST_KEY, String(id));
  } catch {
    // ignore
  }
}

export function AccountField({
  kind,
  accounts,
  value,
  onChange,
  hint,
}: {
  kind: Kind;
  accounts: Holding[];
  value: number | null;
  onChange: (id: number | null) => void;
  hint?: string;
}) {
  if (!accounts.length) return null;
  return (
    <label className="field">
      <span>{kind === "income" ? "Paid into" : "Paid from"}</span>
      <select value={value === null ? "" : String(value)} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
        {accounts.map((a) => (
          <option key={a.id} value={a.id}>{a.name}</option>
        ))}
        <option value="">Not from my accounts</option>
      </select>
      {hint && <span className="hint">{hint}</span>}
    </label>
  );
}
