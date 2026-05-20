import { create } from "zustand";
import { streamChat } from "../api/sse";
import { getBillSections } from "../api/rest";
import { extractRankedBills } from "../lib/rankedBills";
import type {
  BillData,
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
  /** Per-bill section trees, REST-fetched on demand and cached.
   *  Bill text is immutable in v1, so entries are never invalidated. */
  billData: Record<string, BillData>;

  sendPrompt: (message: string) => Promise<void>;
  selectBill: (index: number) => void;
  loadBill: (billId: string) => Promise<void>;
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
  billData: {},

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

  loadBill: async (billId: string) => {
    const existing = get().billData[billId];
    // Skip if already loading or loaded; retry only after an error.
    if (existing && existing.status !== "error") return;

    set((s) => ({
      billData: { ...s.billData, [billId]: { status: "loading" } },
    }));
    try {
      const tree = await getBillSections(billId);
      if (!Array.isArray(tree.sections)) {
        throw new Error("bill not found in corpus");
      }
      set((s) => ({
        billData: { ...s.billData, [billId]: { status: "ready", tree } },
      }));
    } catch (err) {
      set((s) => ({
        billData: {
          ...s.billData,
          [billId]: { status: "error", message: String(err) },
        },
      }));
    }
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
      billData: {},
    }),
}));
