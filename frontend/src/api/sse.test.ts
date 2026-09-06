import { describe, expect, it } from "vitest";
import { parseSseChunk } from "./sse";

describe("parseSseChunk", () => {
  it("parses a single complete event", () => {
    const buf = 'event: message_start\ndata: {"session_id": null}\n\n';
    const { events, remainder } = parseSseChunk(buf);
    expect(events).toEqual([{ type: "message_start", data: { session_id: null } }]);
    expect(remainder).toBe("");
  });

  it("parses multiple events in one chunk", () => {
    const buf =
      'event: agent_started\ndata: {"agent": "router", "message": "Understanding your request"}\n\n' +
      'event: text_delta\ndata: {"text": "Hello"}\n\n';
    const { events, remainder } = parseSseChunk(buf);
    expect(events).toHaveLength(2);
    expect(events[0].type).toBe("agent_started");
    expect(events[1]).toEqual({ type: "text_delta", data: { text: "Hello" } });
    expect(remainder).toBe("");
  });

  it("holds back an incomplete trailing event for the next chunk", () => {
    const buf = 'event: text_delta\ndata: {"text": "partial"}\n\nevent: text_delta\ndata: {"tex';
    const { events, remainder } = parseSseChunk(buf);
    expect(events).toEqual([{ type: "text_delta", data: { text: "partial" } }]);
    expect(remainder).toBe('event: text_delta\ndata: {"tex');
  });

  it("reassembles a split event once the remainder is fed back in", () => {
    const first = parseSseChunk('event: text_delta\ndata: {"tex');
    expect(first.events).toHaveLength(0);
    const second = parseSseChunk(first.remainder + 't": "hello"}\n\n');
    expect(second.events).toEqual([{ type: "text_delta", data: { text: "hello" } }]);
  });

  it("handles event and data lines in either order", () => {
    const buf = 'data: {"text": "x"}\nevent: text_delta\n\n';
    const { events } = parseSseChunk(buf);
    expect(events).toEqual([{ type: "text_delta", data: { text: "x" } }]);
  });

  it("skips a block with malformed JSON instead of throwing", () => {
    const buf =
      "event: text_delta\ndata: {not valid json\n\n" +
      'event: workflow_completed\ndata: {}\n\n';
    const { events } = parseSseChunk(buf);
    expect(events).toEqual([{ type: "workflow_completed", data: {} }]);
  });

  it("ignores blocks with no event line", () => {
    const buf = ': this is a comment\n\nevent: message_complete\ndata: {"answer": "done"}\n\n';
    const { events } = parseSseChunk(buf);
    expect(events).toEqual([{ type: "message_complete", data: { answer: "done" } }]);
  });

  it("returns empty results for an empty buffer", () => {
    const { events, remainder } = parseSseChunk("");
    expect(events).toEqual([]);
    expect(remainder).toBe("");
  });
});
