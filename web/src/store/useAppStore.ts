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
  Turn,
} from "../api/types";

interface AppState {
  /** Every query the user has sent this session, oldest first. The one
   *  the UI is showing is `activeTurnId`; a new prompt always appends. */
  turns: Turn[];
  /** Which turn the answer / bill viewer is currently showing. */
  activeTurnId: string | null;
  /** True while a turn is streaming — only ever the most recent turn. */
  streaming: boolean;
  /** Per-bill section trees, REST-fetched on demand and cached. Bill
   *  text is immutable in v1, so entries are never invalidated — and
   *  the cache is shared across turns. */
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
  retryTurn: (turnId: string) => Promise<void>;
  viewTurn: (turnId: string) => void;
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

/** A stable stand-in for "no turn selected" so consumers never branch
 *  on null. Module-scoped, so its identity is constant. */
const EMPTY_TURN: Turn = {
  id: "",
  prompt: "",
  answerText: "",
  toolCalls: [],
  toolResults: [],
  rankedBills: [],
  errorMessage: null,
  selectedBillIndex: -1,
};

/** The turn the UI is showing. Pure — pass it a state and pick a field
 *  inside a selector (`useAppStore(s => activeTurn(s).answerText)`) so a
 *  field that did not change does not re-render its consumers. */
export function activeTurn(s: AppState): Turn {
  return s.turns.find((t) => t.id === s.activeTurnId) ?? EMPTY_TURN;
}

function makeTurnId(): string {
  return typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `turn-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** A turn reset to its pre-stream state, keeping id and prompt. */
function clearedTurn(turn: Turn): Turn {
  return {
    ...turn,
    answerText: "",
    toolCalls: [],
    toolResults: [],
    rankedBills: [],
    errorMessage: null,
    selectedBillIndex: -1,
  };
}

export const useAppStore = create<AppState>((set, get) => {
  /** Stream a chat response into turn `id`, which must already exist in
   *  `turns`. Shared by sendPrompt (a fresh turn) and retryTurn (an
   *  existing turn re-run in place). */
  const streamInto = async (
    id: string,
    prompt: string,
    history: ChatHistoryItem[],
  ): Promise<void> => {
    const patch = (fn: (t: Turn) => Turn) =>
      set((s) => ({ turns: s.turns.map((t) => (t.id === id ? fn(t) : t)) }));

    // Text streamed before and after a tool call belongs to separate
    // assistant messages; concatenating them directly runs sentences
    // together ('...corpus."No hits...'). Insert a paragraph break the
    // first time text resumes after any tool event.
    let sawToolSinceText = false;

    await streamChat(prompt, history, (event) => {
      switch (event.type) {
        case "text": {
          const sep = sawToolSinceText ? "\n\n" : "";
          sawToolSinceText = false;
          patch((t) => ({
            ...t,
            answerText:
              sep && t.answerText && !t.answerText.endsWith("\n")
                ? t.answerText + sep + event.delta
                : t.answerText + event.delta,
          }));
          break;
        }
        case "tool_call":
          sawToolSinceText = true;
          patch((t) => ({
            ...t,
            toolCalls: [...t.toolCalls, { name: event.name, args: event.args }],
          }));
          break;
        case "tool_result":
          sawToolSinceText = true;
          patch((t) => ({
            ...t,
            toolResults: [
              ...t.toolResults,
              { name: event.name, args: event.args, result: event.result },
            ],
          }));
          break;
        case "error":
          patch((t) => ({ ...t, errorMessage: event.message }));
          break;
        case "done":
          break;
      }
    });

    // Finalize: derive the ranked bill list from the turn's tool results.
    set((s) => ({
      streaming: false,
      turns: s.turns.map((t) => {
        if (t.id !== id) return t;
        const bills = extractRankedBills(t.toolResults);
        return {
          ...t,
          rankedBills: bills,
          selectedBillIndex: bills.length > 0 ? 0 : -1,
        };
      }),
    }));
  };

  /** The conversational context to send for a turn at `beforeIndex`:
   *  the prompts of every earlier turn that actually got an answer. A
   *  turn that errored out produced nothing, so it is skipped. Assistant
   *  text is never re-sent (it would desync the tool_use block pairs). */
  const historyBefore = (beforeIndex: number): ChatHistoryItem[] =>
    get()
      .turns.slice(0, beforeIndex)
      .filter((t) => !t.errorMessage)
      .map((t) => ({ role: "user", content: t.prompt }));

  return {
    turns: [],
    activeTurnId: null,
    streaming: false,
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

      const history = historyBefore(get().turns.length);
      const id = makeTurnId();
      const turn: Turn = {
        id,
        prompt: trimmed,
        answerText: "",
        toolCalls: [],
        toolResults: [],
        rankedBills: [],
        errorMessage: null,
        selectedBillIndex: -1,
      };
      set((s) => ({
        turns: [...s.turns, turn],
        activeTurnId: id,
        streaming: true,
        // A new turn brings a fresh auto mode — drop manual overrides
        // and any stale highlight. Cached bill data (immutable) is kept.
        decompMode: {},
        activeHighlight: null,
      }));
      await streamInto(id, trimmed, history);
    },

    retryTurn: async (turnId: string) => {
      if (get().streaming) return;
      const index = get().turns.findIndex((t) => t.id === turnId);
      if (index === -1) return;
      const prompt = get().turns[index].prompt;

      const history = historyBefore(index);
      // Re-run the turn where it sits — no duplicate row in the list.
      set((s) => ({
        turns: s.turns.map((t) => (t.id === turnId ? clearedTurn(t) : t)),
        activeTurnId: turnId,
        streaming: true,
        decompMode: {},
        activeHighlight: null,
      }));
      await streamInto(turnId, prompt, history);
    },

    viewTurn: (turnId: string) =>
      set((s) =>
        s.turns.some((t) => t.id === turnId)
          ? { activeTurnId: turnId, activeHighlight: null }
          : s,
      ),

    selectBill: (index: number) =>
      set((s) => ({
        turns: s.turns.map((t) => {
          if (t.id !== s.activeTurnId) return t;
          if (index < 0 || index >= t.rankedBills.length) return t;
          return { ...t, selectedBillIndex: index };
        }),
      })),

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
        turns: [],
        activeTurnId: null,
        streaming: false,
        billData: {},
        splitRatio: 0.5,
        scrollRequest: null,
        decompMode: {},
        definedTerms: {},
        amendments: {},
        activeHighlight: null,
      }),
  };
});
