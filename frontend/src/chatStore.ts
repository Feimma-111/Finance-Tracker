// The "Ask a question" conversation, kept outside any component so it survives
// switching tabs and pages, and stored in sessionStorage so it survives a
// reload. sessionStorage is wiped when the browser tab closes, and nothing here
// is ever sent to the database: the conversation lasts for this session only.

import { useSyncExternalStore } from "react";
import { api, type AskResult, type ChatTurn } from "./api";

export type ChatMessage = ChatTurn & { result?: AskResult; error?: boolean };

interface ChatState {
  messages: ChatMessage[];
  busy: boolean;
}

const KEY = "finance-tracker:ask-chat";

function load(): ChatMessage[] {
  try {
    const saved = JSON.parse(sessionStorage.getItem(KEY) ?? "[]");
    return Array.isArray(saved) ? saved : [];
  } catch {
    return [];
  }
}

let state: ChatState = { messages: load(), busy: false };
const listeners = new Set<() => void>();

function set(patch: Partial<ChatState>) {
  state = { ...state, ...patch };
  try {
    sessionStorage.setItem(KEY, JSON.stringify(state.messages));
  } catch {
    // storage blocked (private window): the chat still works until reload
  }
  listeners.forEach((listener) => listener());
}

export function useChat(): ChatState {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => state,
  );
}

/** Ask a question. Keeps running if the user switches tabs while it's thinking. */
export async function sendQuestion(question: string): Promise<void> {
  question = question.trim();
  if (!question || state.busy) return;
  // Earlier turns (text only) give follow-ups like "and in October?" their context.
  const history: ChatTurn[] = state.messages.filter((m) => !m.error).map(({ role, content }) => ({ role, content }));
  set({ messages: [...state.messages, { role: "user", content: question }], busy: true });
  try {
    const result = await api.ask(question, history);
    set({ messages: [...state.messages, { role: "assistant", content: result.answer, result }], busy: false });
  } catch (e) {
    set({ messages: [...state.messages, { role: "assistant", content: (e as Error).message, error: true }], busy: false });
  }
}

export function clearChat(): void {
  set({ messages: [] });
}
