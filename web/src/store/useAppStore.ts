import { create } from "zustand";
import { streamChat } from "../api/sse";
import { getAmendments, getBillSections, getDefinedTerms } from "../api/rest";
import { extractRankedBills } from "../lib/rankedBills";
import type {
  ActiveHighlight,
  AmendmentsResult,
  AsyncResource,
  BillData,
  ChatHistoryItem,
  DecompMode,
  DefinedTermsResult,
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
  /** The most recent prompt sent — lets the error notice offer a retry. */
  lastPrompt: string;
  toolCalls: ToolCall[];
  toolResults: ToolResult[];
  /** Derived from toolResults when the turn completes. */
  rankedBills: RankedBill[];
  /** Index into rankedBills; -1 when the list is empty. */
  selectedBillIndex: number;
  /** Per-bill section trees, REST-fetched on demand and cached.
   *  Bill text is immutable in v1, so entries are never invalidated. */
  billData: Record<string, BillData>;
  /** Text-vs-Decomp column ratio in the bill pane, 0.3–0.7. */
  splitRatio: number;
  /** A request to scroll the Text panel to a section. `seq` makes a
   *  repeat click of the same outline entry still fire the scroll. */
  scrollRequest: { billId: string; sectionId: string; seq: number } | null;
  /** Per-bill manual Decomp-mode override; a missing key means auto. */
  decompMode: Record<string, DecompMode>;
  /** Per-bill defined terms, REST-fetched on demand and cached. */
  definedTerms: Record<string, AsyncResource<DefinedTermsResult>>;
  /** Per-bill amendment operations, REST-fetched on demand and cached. */
  amendments: Record<string, AsyncResource<AmendmentsResult>>;
  /** The one span the synced highlight is focused on, or null. */
  activeHighlight: ActiveHighlight | null;

  sendPrompt: (message: string) => Promise<void>;
  selectBill: (index: number) => void;
  loadBill: (billId: string) => Promise<void>;
  loadDefinedTerms: (billId: string) => Promise<void>;
  loadAmendments: (billId: string) => Promise<void>;
  setSplitRatio: (ratio: number) => void;
  requestScroll: (billId: string, sectionId: string) => void;
  setDecompMode: (billId: string, mode: DecompMode) => void;
  setHighlight: (highlight: Omit<ActiveHighlight, "seq">) => void;
  clearHighlight: () => void;
  reset: () => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  history: [],
  answerText: "",
  streaming: false,
  errorMessage: null,
  lastPrompt: "",
  toolCalls: [],
  toolResults: [],
  rankedBills: [],
  selectedBillIndex: -1,
  billData: {},
  splitRatio: 0.5,
  scrollRequest: null,
  decompMode: {},
  definedTerms: {},
  amendments: {},
  activeHighlight: null,

  sendPrompt: async (message: string) => {
    const trimmed = message.trim();
    if (!trimmed || get().streaming) return;

    const history = get().history;
    set({
      streaming: true,
      errorMessage: null,
      lastPrompt: trimmed,
      answerText: "",
      toolCalls: [],
      toolResults: [],
      rankedBills: [],
      selectedBillIndex: -1,
      // A new turn brings a fresh auto mode — drop manual overrides and
      // any stale highlight. Cached bill data (immutable) is kept.
      decompMode: {},
      activeHighlight: null,
    });

    // Text streamed before and after a tool call belongs to separate
    // assistant messages; concatenating them directly runs sentences
    // together ('...corpus."No hits...'). Insert a paragraph break the
    // first time text resumes after any tool event.
    let sawToolSinceText = false;

    await streamChat(trimmed, history, (event) => {
      switch (event.type) {
        case "text": {
          const sep = sawToolSinceText ? "\n\n" : "";
          sawToolSinceText = false;
          set((s) => ({
            answerText:
              sep && s.answerText && !s.answerText.endsWith("\n")
                ? s.answerText + sep + event.delta
                : s.answerText + event.delta,
          }));
          break;
        }
        case "tool_call":
          sawToolSinceText = true;
          set((s) => ({
            toolCalls: [...s.toolCalls, { name: event.name, args: event.args }],
          }));
          break;
        case "tool_result":
          sawToolSinceText = true;
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

    const errored = get().errorMessage !== null;
    const bills = extractRankedBills(get().toolResults);
    set((s) => ({
      streaming: false,
      // A turn that errored out never produced an answer — keep it out
      // of history so it doesn't count as conversational context.
      history: errored
        ? s.history
        : [...s.history, { role: "user", content: trimmed }],
      rankedBills: bills,
      selectedBillIndex: bills.length > 0 ? 0 : -1,
    }));
  },

  selectBill: (index: number) => {
    const n = get().rankedBills.length;
    if (index >= 0 && index < n) set({ selectedBillIndex: index });
  },

  setSplitRatio: (ratio: number) =>
    set({ splitRatio: Math.min(0.7, Math.max(0.3, ratio)) }),

  requestScroll: (billId: string, sectionId: string) =>
    set((s) => ({
      scrollRequest: {
        billId,
        sectionId,
        seq: (s.scrollRequest?.seq ?? 0) + 1,
      },
    })),

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

  loadDefinedTerms: async (billId: string) => {
    const existing = get().definedTerms[billId];
    if (existing && existing.status !== "error") return;

    set((s) => ({
      definedTerms: { ...s.definedTerms, [billId]: { status: "loading" } },
    }));
    try {
      const result = await getDefinedTerms(billId);
      if (!Array.isArray(result.terms)) {
        throw new Error("malformed definitions response");
      }
      set((s) => ({
        definedTerms: {
          ...s.definedTerms,
          [billId]: { status: "ready", result },
        },
      }));
    } catch (err) {
      set((s) => ({
        definedTerms: {
          ...s.definedTerms,
          [billId]: { status: "error", message: String(err) },
        },
      }));
    }
  },

  loadAmendments: async (billId: string) => {
    const existing = get().amendments[billId];
    if (existing && existing.status !== "error") return;

    set((s) => ({
      amendments: { ...s.amendments, [billId]: { status: "loading" } },
    }));
    try {
      const result = await getAmendments(billId);
      if (!Array.isArray(result.amendments)) {
        throw new Error("malformed amendments response");
      }
      set((s) => ({
        amendments: {
          ...s.amendments,
          [billId]: { status: "ready", result },
        },
      }));
    } catch (err) {
      set((s) => ({
        amendments: {
          ...s.amendments,
          [billId]: { status: "error", message: String(err) },
        },
      }));
    }
  },

  setDecompMode: (billId: string, mode: DecompMode) =>
    set((s) => ({ decompMode: { ...s.decompMode, [billId]: mode } })),

  setHighlight: (highlight) =>
    set((s) => ({
      activeHighlight: {
        ...highlight,
        seq: (s.activeHighlight?.seq ?? 0) + 1,
      },
    })),

  clearHighlight: () => set({ activeHighlight: null }),

  reset: () =>
    set({
      history: [],
      answerText: "",
      streaming: false,
      errorMessage: null,
      lastPrompt: "",
      toolCalls: [],
      toolResults: [],
      rankedBills: [],
      selectedBillIndex: -1,
      billData: {},
      splitRatio: 0.5,
      scrollRequest: null,
      decompMode: {},
      definedTerms: {},
      amendments: {},
      activeHighlight: null,
    }),
}));
