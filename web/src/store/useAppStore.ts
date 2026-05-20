import { create } from "zustand";
import { streamChat } from "../api/sse";
import { extractRankedBills } from "../lib/rankedBills";
import type {
  ChatHistoryItem,
  RankedBill,
  ToolCall,
  ToolResult,
} from "../api/types";

interface AppState {
  /** User turns only — never the rendered assistant answer (it would
   *  desync from the server's tool_use/tool_result block pairs). */
  history: ChatHistoryItem[];
  /** The current turn's streaming answer text. */
  answerText: string;
  streaming: boolean;
  errorMessage: string | null;
  toolCalls: ToolCall[];
  toolResults: ToolResult[];
  /** Derived from toolResults when the turn completes. */
  rankedBills: RankedBill[];
  /** Index into rankedBills; -1 when the list is empty. */
  selectedBillIndex: number;

  sendPrompt: (message: string) => Promise<void>;
  selectBill: (index: number) => void;
  reset: () => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  history: [],
  answerText: "",
  streaming: false,
  errorMessage: null,
  toolCalls: [],
  toolResults: [],
  rankedBills: [],
  selectedBillIndex: -1,

  sendPrompt: async (message: string) => {
    const trimmed = message.trim();
    if (!trimmed || get().streaming) return;

    const history = get().history;
    set({
      streaming: true,
      errorMessage: null,
      answerText: "",
      toolCalls: [],
      toolResults: [],
      rankedBills: [],
      selectedBillIndex: -1,
    });

    await streamChat(trimmed, history, (event) => {
      switch (event.type) {
        case "text":
          set((s) => ({ answerText: s.answerText + event.delta }));
          break;
        case "tool_call":
          set((s) => ({
            toolCalls: [...s.toolCalls, { name: event.name, args: event.args }],
          }));
          break;
        case "tool_result":
          set((s) => ({
            toolResults: [
              ...s.toolResults,
              { name: event.name, args: event.args, result: event.result },
            ],
          }));
          break;
        case "error":
          set({ errorMessage: event.message });
          break;
        case "done":
          break;
      }
    });

    const bills = extractRankedBills(get().toolResults);
    set((s) => ({
      streaming: false,
      history: [...s.history, { role: "user", content: trimmed }],
      rankedBills: bills,
      selectedBillIndex: bills.length > 0 ? 0 : -1,
    }));
  },

  selectBill: (index: number) => {
    const n = get().rankedBills.length;
    if (index >= 0 && index < n) set({ selectedBillIndex: index });
  },

  reset: () =>
    set({
      history: [],
      answerText: "",
      streaming: false,
      errorMessage: null,
      toolCalls: [],
      toolResults: [],
      rankedBills: [],
      selectedBillIndex: -1,
    }),
}));
