import { useState, type FormEvent } from "react";
import { api, type AiStatus, type Goal, type SavingsCheck } from "../api";
import { currencySymbol, dateCompact, dateLabel, displayCurrency, money, moneyIn } from "../format";
import { useAsync, type AsyncState } from "../hooks";
import { useCashAccounts } from "./AccountField";
import { AiStatusLine, isOnline } from "./AiParts";
import { DateInput } from "./DateInput";
import { FollowUpChat } from "./FollowUpChat";
import { Sheet } from "./Sheet";

/* Savings goals ("Japan trip, $1,500 by June"), each with what it needs per
   month, plus the AI's savings check: from your pay, recorded income, the
   spending you control and your goals, how much you can save -- all the
   numbers worked out by the app, described by the model on your PC. */

export function GoalsCard({ version, onChanged, status }: { version: number; onChanged: () => void; status: AsyncState<AiStatus> }) {
  const goals = useAsync(api.goals, [version]);
  const [editing, setEditing] = useState<Goal | "new" | null>(null);
  const list = goals.data ?? [];

  return (
    <section className={`card ${goals.loading && goals.data ? "refreshing" : ""}`} style={{ marginTop: 16 }}>
      <div className="card-head">
        <h2 className="card-title">Savings goals</h2>
        <button className="btn btn-small card-action" type="button" onClick={() => setEditing("new")}>Add goal</button>
      </div>
      {goals.error && <p className="message error">{goals.error}</p>}
      {goals.data && !list.length && (
        <p className="hint" style={{ margin: 0 }}>
          Saving for something, like a trip or a laptop? Add it with an amount and a date, and you'll see how much to
          put aside each month.
        </p>
      )}
      {list.length > 0 && (
        <ul className="goal-list">
          {list.map((goal) => (
            <GoalRow key={goal.id} goal={goal} onEdit={() => setEditing(goal)} />
          ))}
        </ul>
      )}
      <SavingsCheckPanel status={status} hasGoals={list.length > 0} />
      {editing && (
        <GoalSheet
          goal={editing === "new" ? null : editing}
          version={version}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            onChanged();
          }}
        />
      )}
    </section>
  );
}

function GoalRow({ goal, onEdit }: { goal: Goal; onEdit: () => void }) {
  const done = goal.left_cents === 0;
  const share = goal.share ?? 0;
  let plan: string;
  if (goal.target_cents === null) plan = `Couldn't get the ${goal.currency} exchange rate right now.`;
  else if (done) plan = "Reached. Nice work!";
  else if (!goal.target_date) plan = `${money(goal.left_cents ?? 0)} to go · no date set`;
  else if (goal.months_left !== null && goal.months_left <= 0) plan = `${money(goal.left_cents ?? 0)} to go · the date has passed`;
  else plan = `${money(goal.per_month_cents ?? 0)} a month to reach it by ${dateCompact(goal.target_date)}`;

  return (
    <li>
      <button type="button" className={`goal ${done ? "done" : ""}`} onClick={onEdit} aria-label={`Edit ${goal.name}`}>
        <span className="goal-icon" aria-hidden="true">{done ? "🎉" : "🎯"}</span>
        <span className="goal-main">
          <span className="goal-top">
            <strong>{goal.name}</strong>
            {goal.saved_cents !== null && goal.target_cents !== null && (
              <span className="num">
                {money(goal.saved_cents)} <span className="subtle">of {money(goal.target_cents)}</span>
              </span>
            )}
          </span>
          <span className="goal-track" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(share * 100)}
            aria-label={`${goal.name}: ${Math.round(share * 100)}% saved`}>
            <span className="goal-fill" style={{ width: `${share * 100}%` }} />
          </span>
          <span className="goal-bottom">
            <span>{plan}</span>
            <span className="subtle">{goal.account_name ? `In ${goal.account_name}` : "Set aside by hand"}</span>
          </span>
        </span>
      </button>
    </li>
  );
}

function GoalSheet({ goal, version, onClose, onSaved }: { goal: Goal | null; version: number; onClose: () => void; onSaved: () => void }) {
  const accounts = useCashAccounts(version);
  const currency = goal?.currency ?? displayCurrency();
  const whole = currency === "TWD" || currency === "JPY" || currency === "KRW";
  const amount = (cents: number) => (cents / 100).toFixed(whole ? 0 : 2);
  const [name, setName] = useState(goal?.name ?? "");
  const [target, setTarget] = useState(goal ? amount(goal.target_set_cents) : "");
  const [date, setDate] = useState(goal?.target_date ?? "");
  const [account, setAccount] = useState<number | null>(goal?.account_id ?? null);
  const [saved, setSaved] = useState(goal && !goal.account_id ? amount(goal.saved_set_cents) : "");
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const body = { name, target, currency, target_date: date, account_id: account, saved: account === null ? saved : "" };
    try {
      if (goal) await api.updateGoal(goal.id, body);
      else await api.addGoal(body);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  async function remove() {
    if (!goal) return;
    setBusy(true);
    try {
      await api.deleteGoal(goal.id);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <Sheet title={goal ? `Edit ${goal.name}` : "New savings goal"} onClose={onClose}>
      <form className="form" onSubmit={save}>
        <label className="field">
          <span>What for</span>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Japan trip" required maxLength={80} />
        </label>
        <div className="field-row">
          <label className="field">
            <span>Amount</span>
            <div className="money-input">
              <i>{currencySymbol(currency)}</i>
              <input type="text" inputMode="decimal" value={target} onChange={(e) => setTarget(e.target.value)} placeholder="0" required />
            </div>
          </label>
          <label className="field">
            <span>By (optional)</span>
            <DateInput value={date} onChange={setDate} min={new Date().toISOString().slice(0, 10)} max="2100-12-31" />
          </label>
        </div>
        <label className="field">
          <span>Progress comes from</span>
          <select value={account ?? ""} onChange={(e) => setAccount(e.target.value ? Number(e.target.value) : null)}>
            <option value="">An amount I enter</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>The balance of {a.name}</option>
            ))}
          </select>
          <span className="hint">
            {account === null
              ? "Update it whenever you put more aside."
              : "A savings account just for this works best: its balance is your progress."}
          </span>
        </label>
        {account === null && (
          <label className="field">
            <span>Saved so far</span>
            <div className="money-input">
              <i>{currencySymbol(currency)}</i>
              <input type="text" inputMode="decimal" value={saved} onChange={(e) => setSaved(e.target.value)} placeholder="0" />
            </div>
          </label>
        )}
        {error && <p className="message error" style={{ margin: 0 }}>{error}</p>}
        <button className="btn btn-primary" type="submit" disabled={busy}>{goal ? "Save" : "Add goal"}</button>
        {goal && (
          <div className="sheet-danger">
            {confirmRemove ? (
              <>
                <span className="subtle">Remove {goal.name}?</span>
                <button type="button" className="btn btn-small btn-danger" onClick={remove} disabled={busy}>Remove</button>
                <button type="button" className="btn btn-small" onClick={() => setConfirmRemove(false)}>Keep</button>
              </>
            ) : (
              <button type="button" className="btn-link danger-link" onClick={() => setConfirmRemove(true)}>Remove goal</button>
            )}
          </div>
        )}
      </form>
    </Sheet>
  );
}

/* ------------------------------------------------------------------ the AI's savings check */

const CHECK_KEY = "finance-tracker:savings-check";
const FOLLOW_UPS = ["How can I reach my goals sooner?", "How many hours do I work for my food spending?", "What if I worked 5 more hours a week?"];

function savedCheck(): SavingsCheck | null {
  try {
    return JSON.parse(sessionStorage.getItem(CHECK_KEY) ?? "null");
  } catch {
    return null;
  }
}

function SavingsCheckPanel({ status, hasGoals }: { status: AsyncState<AiStatus>; hasGoals: boolean }) {
  const settings = useAsync(api.settings, []);
  const [result, setResult] = useState<SavingsCheck | null>(savedCheck);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const online = isOnline(status.data);
  const income = settings.data?.income;

  async function check() {
    setBusy(true);
    setError(null);
    try {
      const next = await api.savingsCheck();
      setResult(next);
      try {
        sessionStorage.setItem(CHECK_KEY, JSON.stringify(next));
      } catch {
        // storage blocked: it still shows until reload
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const section = (title: string, items: string[]) =>
    items.length > 0 && (
      <div>
        <h3 className="ai-heading">{title}</h3>
        <ul>{items.map((item, i) => <li key={i}>{item}</li>)}</ul>
      </div>
    );

  return (
    <div className="savings-check">
      <div className="activity-head">
        <strong>AI savings check</strong>
        {online && (
          <button className="btn btn-small btn-primary" type="button" onClick={check} disabled={busy}>
            {busy ? "Thinking…" : result ? "Check again" : "How much can I save?"}
          </button>
        )}
      </div>
      <AiStatusLine status={status} />
      {income && !income.hourly_cents && (
        <p className="hint" style={{ margin: 0 }}>
          Add your hourly pay in <a href="#/settings">Settings → Your pay</a> so the check can use it (and say what each
          goal costs in hours of work).
        </p>
      )}
      {income?.monthly_cents && (
        <p className="hint" style={{ margin: 0 }}>
          Using your pay: {moneyIn(income.hourly_cents ?? 0, income.currency)} an hour × {income.hours_per_week} hours a week,
          about {moneyIn(income.monthly_cents, income.currency)} a month take-home.
        </p>
      )}
      {busy && <p className="hint" style={{ margin: 0 }}>Asking the model on your PC. This usually takes 5–30 seconds.</p>}
      {error && <p className="message error" style={{ margin: 0 }}>{error}</p>}
      {result ? (
        <div className={`ai-review ${busy ? "refreshing" : ""}`}>
          <p className="ai-headline">{result.review.headline}</p>
          <div className="grid grid-2 ai-columns">
            {section("What you can save", result.review.can_save)}
            {section(hasGoals ? "Your goals" : "Goals", result.review.goals)}
          </div>
          <div style={{ marginTop: 14 }}>{section("Ideas", result.review.ideas)}</div>
          <p className="subtle ai-meta">
            Written {dateLabel(result.created_at.slice(0, 10))} by {result.model}. AI can make mistakes, and this isn't
            financial advice.
          </p>
          <details className="table-view">
            <summary>What the AI was shown</summary>
            <pre className="ai-facts">{result.facts}</pre>
          </details>
          <FollowUpChat
            chatKey={`savings:${result.created_at}`}
            analysis={[result.review.headline, ...result.review.can_save, ...result.review.goals, "Ideas:", ...result.review.ideas].join("\n")}
            about={{ savings: true }}
            online={online}
            suggestions={FOLLOW_UPS}
          />
        </div>
      ) : (
        !busy && (
          <p className="hint" style={{ margin: 0 }}>
            The app works out what you typically earn, what you spend that's under your control, what's left over,
            and what each goal needs per month. Then the model says what you can realistically save.
          </p>
        )
      )}
    </div>
  );
}
