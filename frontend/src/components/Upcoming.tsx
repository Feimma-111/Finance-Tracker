import { api } from "../api";
import { dateShort, FREQUENCIES, moneyIn, todayIso } from "../format";
import { useAsync } from "../hooks";
import { CategoryIcon } from "../icons";

const WINDOW_DAYS = 30;

function daysUntil(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  const [ty, tm, td] = todayIso().split("-").map(Number);
  return Math.round((Date.UTC(y, m - 1, d) - Date.UTC(ty, tm - 1, td)) / 86_400_000);
}

function when(days: number): string {
  if (days <= 0) return "Today";
  if (days === 1) return "Tomorrow";
  return `In ${days} days`;
}

/** Recurring bills and paychecks due in the next 30 days (Rocket Money's "Upcoming"). */
export function Upcoming({ version }: { version: number }) {
  const rules = useAsync(api.recurring, [version]);
  const due = (rules.data ?? [])
    .filter((r) => r.active && daysUntil(r.next_due) <= WINDOW_DAYS)
    .sort((a, b) => a.next_due.localeCompare(b.next_due));

  if (rules.data && !due.length) {
    return (
      <p className="hint" style={{ margin: 0 }}>
        Nothing due in the next 30 days. Choose a “Repeat” option when adding rent, subscriptions, or paychecks and
        they'll show up here.
      </p>
    );
  }

  return (
    <ul className="upcoming">
      {due.map((rule) => (
        <li key={rule.id}>
          <CategoryIcon category={rule.category} hint={rule.description} size={34} />
          <div className="tx-main">
            <span className="tx-name">{rule.description}</span>
            <span className="tx-sub" title={`Next on ${dateShort(rule.next_due)}`}>
              {when(daysUntil(rule.next_due))} · {FREQUENCIES.find((f) => f.value === rule.frequency)?.label}
            </span>
          </div>
          <span className={`tx-amount num ${rule.kind === "income" ? "amount-income" : ""}`}>
            {rule.kind === "income" ? "+" : ""}{moneyIn(rule.amount_cents, rule.currency)}
          </span>
        </li>
      ))}
    </ul>
  );
}
