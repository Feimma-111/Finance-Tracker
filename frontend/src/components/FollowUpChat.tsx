import { useState, useSyncExternalStore, type FormEvent } from "react";
import { api, type AskAbout, type ChatTurn, type ReviewText } from "../api";
import type { ChatMessage } from "../chatStore";
import { ChatThread } from "./AiAsk";

/* Follow-up questions on something the AI wrote: the monthly review, or the
   look at ticked categories. The server gives the model that analysis's fact
   sheet as context (and the lookup tools), and this conversation as history.

   Conversations live outside the components (a question keeps going if you
   switch pages) and in sessionStorage (they survive a reload), keyed by the
   analysis they're about -- a new analysis starts a new conversation. Like
   the main chat, nothing is saved to the database. */

const KEY = "finance-tracker:follow-ups";
const MAX_KEPT = 30;

interface State {
  chats: Record<string, ChatMessage[]>;
  asking: Record<string, true>;
}

function load(): Record<string, ChatMessage[]> {
  try {
    const saved = JSON.parse(sessionStorage.getItem(KEY) ?? "{}");
    return saved && typeof saved === "object" && !Array.isArray(saved) ? saved : {};
  } catch {
    return {};
  }
}

let state: State = { chats: load(), asking: {} };
const listeners = new Set<() => void>();

function set(next: State) {
  state = next;
  try {
    const kept = Object.entries(state.chats).slice(-MAX_KEPT); // insertion order: newest last
    sessionStorage.setItem(KEY, JSON.stringify(Object.fromEntries(kept)));
  } catch {
    // storage blocked (private window): the chat still works until reload
  }
  listeners.forEach((listener) => listener());
}

function useFollowUps(): State {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => state,
  );
}

/** What the AI wrote, as plain text, so the model knows what it said before. */
export function reviewText(review: ReviewText): string {
  const { headline, observations, suggestions } = review;
  return [headline, ...observations.map((o) => `- ${o}`), "Ideas:", ...suggestions.map((s) => `- ${s}`)].join("\n");
}

async function askFollowUp(chatKey: string, question: string, analysis: string, about: AskAbout): Promise<void> {
  question = question.trim();
  if (!question || state.asking[chatKey]) return;
  const earlier = state.chats[chatKey] ?? [];
  const history: ChatTurn[] = [
    { role: "assistant", content: analysis },
    ...earlier.filter((m) => !m.error).map(({ role, content }) => ({ role, content })),
  ];
  const withQuestion: ChatMessage[] = [...earlier, { role: "user", content: question }];
  set({ chats: { ...state.chats, [chatKey]: withQuestion }, asking: { ...state.asking, [chatKey]: true } });
  let reply: ChatMessage;
  try {
    const answer = await api.ask(question, history, about);
    reply = { role: "assistant", content: answer.answer, result: answer };
  } catch (e) {
    reply = { role: "assistant", content: (e as Error).message, error: true };
  }
  const { [chatKey]: _, ...asking } = state.asking;
  set({ chats: { ...state.chats, [chatKey]: [...withQuestion, reply] }, asking });
}

/** "Ask about this": suggestions to start, then the conversation and a box to ask more. */
export function FollowUpChat({
  chatKey,
  analysis,
  about,
  online,
  suggestions,
}: {
  chatKey: string; // one conversation per analysis
  analysis: string; // what the AI wrote (see reviewText)
  about: AskAbout; // which fact sheet the server uses as context
  online: boolean;
  suggestions: string[];
}) {
  const all = useFollowUps();
  const messages = all.chats[chatKey] ?? [];
  const busy = !!all.asking[chatKey];
  const [draft, setDraft] = useState("");

  function send(question: string) {
    if (!question.trim() || busy) return;
    setDraft("");
    askFollowUp(chatKey, question, analysis, about);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    send(draft);
  }

  return (
    <div className="follow-up">
      <h3 className="ai-heading">Ask about this</h3>
      {messages.length > 0 ? (
        <ChatThread messages={messages} busy={busy} />
      ) : (
        <div className="chips">
          {suggestions.map((q) => (
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
