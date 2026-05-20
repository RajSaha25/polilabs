import type { ChatHistoryItem, SSEEvent } from "./types";

/** Stream a chat turn from POST /chat.
 *
 * The backend emits Server-Sent Events (`data: {...}\n\n`). We read the
 * response body as a stream, split on the blank-line delimiter, and
 * hand each parsed event to `onEvent`. Malformed frames are skipped
 * rather than thrown — a dropped event must never abort the stream. */
export async function streamChat(
  message: string,
  history: ChatHistoryItem[],
  onEvent: (event: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history }),
      signal,
    });
  } catch (err) {
    onEvent({ type: "error", message: `request failed: ${String(err)}` });
    return;
  }

  if (!res.ok || !res.body) {
    onEvent({ type: "error", message: `backend returned HTTP ${res.status}` });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? ""; // last item is the incomplete frame
    for (const frame of frames) {
      const line = frame.trim();
      if (!line.startsWith("data:")) continue;
      const payload = line.slice(5).trim();
      if (!payload) continue;
      try {
        onEvent(JSON.parse(payload) as SSEEvent);
      } catch {
        // skip a malformed frame; keep streaming
      }
    }
  }
}
