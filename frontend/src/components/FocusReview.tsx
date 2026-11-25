import { useSyncExternalStore } from "react";
import { api, type AiStatus, type FocusResult } from "../api";
import { monthLabel } from "../format";
import { useAsync, type AsyncState } from "../hooks";
import { AiStatusLine, isOnline, ReviewBody } from "./AiParts";
import { FollowUpChat, reviewText } from "./FollowUpChat";

/* The AI's look at only the categories chosen on the dashboard.

   Results live outside the component (so a request keeps going if you switch
   pages) and in sessionStorage (so they survive a reload), keyed by month and
   category set: go back to "Food + Transport in October" and its analysis is
   still there. Like the question chat, nothing is saved to the database, and
   closing the tab clears it. */

const KEY = "finance-tracker:focus-reviews";
const MAX_KEPT = 20;

interface FocusState {
  results: Record<string, FocusResult>;
  busy: Record<string, true>;
  errors: Record<string, string>;
}

function load(): Record<string, FocusResult> {
  try {
    const saved = JSON.parse(sessionStorage.getItem(KEY) ?? "{}");
    return saved && typeof saved === "object" && !Array.isArray(saved) ? saved : {};
  } catch {
    return {};
  }
}

let state: FocusState = { results: load(), busy: {}, errors: {} };
const listeners = new Set<() => void>();

function set(next: FocusState) {
  state = next;
  try {
    const newest = Object.entries(state.results)
      .sort(([, a], [, b]) => b.created_at.localeCompare(a.created_at))
      .slice(0, MAX_KEPT);
    sessionStorage.setItem(KEY, JSON.stringify(Object.fromEntries(newest)));
  } catch {
    // storage blocked (private window): results still show until reload
  }
  listeners.forEach((listener) => listener());
}

function without<T>(record: Record<string, T>, key: string): Record<string, T> {
  const { [key]: _, ...rest } = record;
  return rest;
}

/** Same month and same categories (in any order, any capitalization) = same key. */
function keyFor(month: string, categories: string[]): string {
  return JSON.stringify([month, categories.map((c) => c.toLowerCase()).sort()]);
}

/** Run the analysis (also used by a cap's "Why?"). */
export async function analyze(month: string, categories: string[]): Promise<void> {
  const key = keyFor(month, categories);
  if (state.busy[key]) return;
  set({ ...state, busy: { ...state.busy, [key]: true }, errors: without(state.errors, key) });
  try {
    const result = await api.focusReview(month, categories);
    set({ ...state, results: { ...state.results, [key]: result }, busy: without(state.busy, key) });
  } catch (e) {
    set({ ...state, errors: { ...state.errors, [key]: (e as Error).message }, busy: without(state.busy, key) });
  }
}

const FOLLOW_UPS = ["What should I cut back on first?", "How does this compare with last month?", "Which purchase grew the most?"];

function useFocusState(): FocusState {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => state,
  );
}

/** "Food", "Food and Transport", "Food, Transport and Fun". */
export function listNames(names: string[]): string {
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** Short enough for one button: names only for one or two categories. */
function analyzeLabel(categories: string[], everything: boolean): string {
  if (everything) return "Analyze all categories";
  if (categories.length <= 2) return `Analyze ${listNames(categories)}`;
  return `Analyze these ${categories.length} categories`;
}

export function FocusReview({
  month,
  categories,
  everything = false,
  status,
  version,
}: {
  month: string;
  categories: string[];
  everything?: boolean; // every category is ticked
  status: AsyncState<AiStatus>;
  version: number;
}) {
  const all = useFocusState();
  // When the data last changed, to flag an analysis written before that.
  const changed = useAsync(api.aiChanged, [version]);
  const key = keyFor(month, categories);
  const result = all.results[key];
  const busy = !!all.busy[key];
  const error = all.errors[key];
  const online = isOnline(status.data);
  const changedAt = changed.data?.changed_at;
  const outdated = !!(result && changedAt && Date.parse(changedAt) > Date.parse(result.created_at));

  return (
    <div className="focus-ai" aria-live="polite">
      <h3>AI on {everything ? "all categories" : categories.length ? "these categories" : "ticked categories"}</h3>
      <AiStatusLine status={status} />

      {!categories.length ? (
        <p className="hint">
          Tick one or more categories above, and the AI will look at just those for {monthLabel(month)}: what drove
          the spending, how it compares with earlier months, and ideas for those categories only.
        </p>
      ) : (
        <>
          {online && (
            <div>
              <button className="btn btn-small btn-primary" onClick={() => analyze(month, categories)} disabled={busy}>
                {busy ? "Thinking…" : result ? "Analyze again" : analyzeLabel(categories, everything)}
              </button>
            </div>
          )}
          {busy && <p className="hint">Asking the model on your PC. This usually takes 5–30 seconds.</p>}
          {error && <p className="message error" style={{ margin: 0 }}>{error}</p>}
          {result ? (
            <div className={`ai-review ${busy ? "refreshing" : ""}`}>
              {outdated && (
                <div className="notice">
                  <span>Your transactions or covered expenses changed after this was written, so it may not reflect them.</span>
                </div>
              )}
              <ReviewBody review={result.review} model={result.model} createdAt={result.created_at} facts={result.facts} />
              {/* Keyed by when it was written, so a new analysis starts a new conversation. */}
              <FollowUpChat
                chatKey={`focus:${key}:${result.created_at}`}
                analysis={reviewText(result.review)}
                about={{ focus: { month, categories } }}
                online={online}
                suggestions={FOLLOW_UPS}
              />
            </div>
          ) : (
            !busy && !online && status.data && (
              <p className="hint">Analyses you run are kept here until you close this tab.</p>
            )
          )}
        </>
      )}
    </div>
  );
}
