import { useState, useSyncExternalStore, type FormEvent } from "react";
import { api, type AiStatus, type ChatTurn, type FocusResult } from "../api";
import type { ChatMessage } from "../chatStore";
import { monthLabel } from "../format";
import { useAsync, type AsyncState } from "../hooks";
import { ChatThread } from "./AiAsk";
import { AiStatusLine, isOnline, ReviewBody } from "./AiParts";

/* The AI's look at only the categories chosen on the dashboard.

   Results live outside the component (so a request keeps going if you switch
   pages) and in sessionStorage (so they survive a reload), keyed by month and
   category set: go back to "Food + Transport in October" and its analysis is
   still there. Like the question chat, nothing is saved to the database, and
   closing the tab clears it. */

const KEY = "finance-tracker:focus-reviews";
const CHAT_KEY = "finance-tracker:focus-chats";
const MAX_KEPT = 20;

interface FocusState {
  results: Record<string, FocusResult>;
  chats: Record<string, ChatMessage[]>; // follow-up questions on each analysis
  busy: Record<string, true>;
  asking: Record<string, true>;
  errors: Record<string, string>;
}

function load<T>(key: string): Record<string, T> {
  try {
    const saved = JSON.parse(sessionStorage.getItem(key) ?? "{}");
    return saved && typeof saved === "object" && !Array.isArray(saved) ? saved : {};
  } catch {
    return {};
  }
}

let state: FocusState = { results: load(KEY), chats: load(CHAT_KEY), busy: {}, asking: {}, errors: {} };
const listeners = new Set<() => void>();

function set(next: FocusState) {
  state = next;
  try {
    const newest = Object.entries(state.results)
      .sort(([, a], [, b]) => b.created_at.localeCompare(a.created_at))
      .slice(0, MAX_KEPT);
    sessionStorage.setItem(KEY, JSON.stringify(Object.fromEntries(newest)));
    const kept = new Set(newest.map(([key]) => key));
    sessionStorage.setItem(CHAT_KEY, JSON.stringify(
      Object.fromEntries(Object.entries(state.chats).filter(([key]) => kept.has(key))),
    ));
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

async function analyze(month: string, categories: string[]): Promise<void> {
  const key = keyFor(month, categories);
  if (state.busy[key]) return;
  set({ ...state, busy: { ...state.busy, [key]: true }, errors: without(state.errors, key) });
  try {
    const result = await api.focusReview(month, categories);
    // A new analysis starts a new conversation.
    set({ ...state, results: { ...state.results, [key]: result }, chats: without(state.chats, key), busy: without(state.busy, key) });
  } catch (e) {
    set({ ...state, errors: { ...state.errors, [key]: (e as Error).message }, busy: without(state.busy, key) });
  }
}

/** The analysis as plain text, so the model knows what it said before. */
function reviewText(result: FocusResult): string {
  const { headline, observations, suggestions } = result.review;
  return [headline, ...observations.map((o) => `- ${o}`), "Ideas:", ...suggestions.map((s) => `- ${s}`)].join("\n");
}

/** A follow-up question on one analysis. The server rebuilds its fact sheet as context. */
async function askFollowUp(month: string, categories: string[], question: string): Promise<void> {
  const key = keyFor(month, categories);
  const result = state.results[key];
  question = question.trim();
  if (!question || !result || state.asking[key]) return;
  const earlier = state.chats[key] ?? [];
  const history: ChatTurn[] = [
    { role: "assistant", content: reviewText(result) },
    ...earlier.filter((m) => !m.error).map(({ role, content }) => ({ role, content })),
  ];
  const withQuestion: ChatMessage[] = [...earlier, { role: "user", content: question }];
  set({ ...state, chats: { ...state.chats, [key]: withQuestion }, asking: { ...state.asking, [key]: true } });
  let reply: ChatMessage;
  try {
    const answer = await api.ask(question, history, { month, categories });
    reply = { role: "assistant", content: answer.answer, result: answer };
  } catch (e) {
    reply = { role: "assistant", content: (e as Error).message, error: true };
  }
  set({ ...state, chats: { ...state.chats, [key]: [...withQuestion, reply] }, asking: without(state.asking, key) });
}

const FOLLOW_UPS = ["What should I cut back on first?", "How does this compare with last month?", "Which purchase grew the most?"];

/** Ask the AI more about one analysis. */
function FocusChat({ month, categories, online }: { month: string; categories: string[]; online: boolean }) {
  const all = useFocusState();
  const key = keyFor(month, categories);
  const messages = all.chats[key] ?? [];
  const busy = !!all.asking[key];
  const [draft, setDraft] = useState("");

  function send(question: string) {
    if (!question.trim() || busy) return;
    setDraft("");
    askFollowUp(month, categories, question);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    send(draft);
  }

  return (
    <div className="focus-chat">
      <h3 className="ai-heading">Ask about this</h3>
      {messages.length > 0 ? (
        <ChatThread messages={messages} busy={busy} />
      ) : (
        <div className="chips">
          {FOLLOW_UPS.map((q) => (
            <button key={q} type="button" className="chip" disabled={!online} onClick={() => send(q)}>{q}</button>
          ))}
        </div>
      )}
      <form className="inline-form ask-form" onSubmit={submit}>
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={online ? "Ask a follow-up…" : "Your PC needs to be on to answer"}
          disabled={!online}
          maxLength={500}
          aria-label="Follow-up question about this analysis"
        />
        <button className="btn btn-primary" type="submit" disabled={!online || busy || !draft.trim()}>
          {busy ? "Asking…" : "Ask"}
        </button>
      </form>
    </div>
  );
}

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
              <FocusChat month={month} categories={categories} online={online} />
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
