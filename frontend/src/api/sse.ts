import type { ChatStreamEvent } from "../types";

/**
 * Incrementally parses Server-Sent Events out of a raw text buffer.
 * SSE events are separated by a blank line; each event has an
 * `event: <type>` line and a `data: <json>` line (in either order).
 * Returns the parsed events found in `buffer` plus whatever incomplete
 * tail remains (to be prepended to the next chunk) - this is the exact
 * shape needed to drive a streaming `fetch` reader loop, but it takes
 * a plain string and returns plain data, so it can be tested without
 * any network or browser API at all.
 */
export function parseSseChunk(buffer: string): {
  events: ChatStreamEvent[];
  remainder: string;
} {
  const events: ChatStreamEvent[] = [];
  const blocks = buffer.split("\n\n");
  // The last element is either "" (buffer ended exactly on a boundary)
  // or an incomplete trailing event - keep it for next time either way.
  const remainder = blocks.pop() ?? "";

  for (const block of blocks) {
    if (!block.trim()) continue;
    let eventType: string | null = null;
    let dataLine: string | null = null;
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) {
        eventType = line.slice("event:".length).trim();
      } else if (line.startsWith("data:")) {
        dataLine = line.slice("data:".length).trim();
      }
    }
    if (!eventType) continue;
    let data: Record<string, unknown> = {};
    if (dataLine) {
      try {
        data = JSON.parse(dataLine);
      } catch {
        // Malformed event from the server - skip it rather than crash
        // the whole stream over one bad line.
        continue;
      }
    }
    events.push({ type: eventType as ChatStreamEvent["type"], data });
  }

  return { events, remainder };
}
