import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { useChat } from "./useChat";
import type { ChatStreamEvent } from "../types";
import { api } from "../api/client";

vi.mock("../api/client", () => ({
  api: { streamChat: vi.fn() },
}));

const mockedStreamChat = vi.mocked(api.streamChat);

function scriptEvents(events: ChatStreamEvent[]) {
  mockedStreamChat.mockImplementation(async (_msg, _sid, onEvent) => {
    for (const e of events) onEvent(e);
  });
}

describe("useChat", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("appends a user message and a streaming assistant message immediately on send", async () => {
    let resolveStream: () => void = () => {};
    mockedStreamChat.mockImplementation(
      () => new Promise((resolve) => { resolveStream = () => resolve(undefined); }),
    );

    const { result } = renderHook(() => useChat(null, vi.fn()));
    act(() => {
      result.current.send("hello there");
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0]).toMatchObject({ role: "user", text: "hello there" });
    expect(result.current.messages[1]).toMatchObject({ role: "assistant", isStreaming: true });
    expect(result.current.sending).toBe(true);

    await act(async () => {
      resolveStream();
    });
  });

  it("accumulates text_delta chunks into the assistant message and finalizes on message_complete", async () => {
    scriptEvents([
      { type: "message_start", data: {} },
      { type: "agent_started", data: { agent: "router", message: "Understanding your request" } },
      { type: "tool_started", data: { tool: "info_retriever", message: "Searching" } },
      { type: "tool_completed", data: { tool: "info_retriever" } },
      { type: "text_delta", data: { text: "Hello, " } },
      { type: "text_delta", data: { text: "world." } },
      { type: "workflow_completed", data: {} },
      { type: "message_complete", data: { answer: "Hello, world.", session_id: null } },
    ]);

    const { result } = renderHook(() => useChat(null, vi.fn()));
    await act(async () => {
      await result.current.send("hi");
    });

    const assistantMsg = result.current.messages.find((m) => m.role === "assistant")!;
    expect(assistantMsg.text).toBe("Hello, world.");
    expect(assistantMsg.isStreaming).toBe(false);
    expect(result.current.sending).toBe(false);

    // tool_started then tool_completed should mark that activity step done
    const toolStep = result.current.activity.find((s) => s.key === "info_retriever");
    expect(toolStep?.done).toBe(true);
  });

  it("calls onSessionCreated when message_complete carries a new session_id and none was set", async () => {
    scriptEvents([
      { type: "message_start", data: {} },
      { type: "text_delta", data: { text: "Started!" } },
      { type: "message_complete", data: { answer: "Started!", session_id: "prj_new_123" } },
    ]);

    const onSessionCreated = vi.fn();
    const { result } = renderHook(() => useChat(null, onSessionCreated));
    await act(async () => {
      await result.current.send("start a project");
    });

    expect(onSessionCreated).toHaveBeenCalledWith("prj_new_123");
  });

  it("does not call onSessionCreated when a session_id was already active", async () => {
    scriptEvents([
      { type: "text_delta", data: { text: "ok" } },
      { type: "message_complete", data: { answer: "ok", session_id: "prj_existing" } },
    ]);

    const onSessionCreated = vi.fn();
    const { result } = renderHook(() => useChat("prj_existing", onSessionCreated));
    await act(async () => {
      await result.current.send("continue");
    });

    expect(onSessionCreated).not.toHaveBeenCalled();
  });

  it("marks the assistant message as an error on an error event, without crashing", async () => {
    scriptEvents([
      { type: "message_start", data: {} },
      { type: "error", data: { message: "Internal server error while processing your message." } },
    ]);

    const { result } = renderHook(() => useChat(null, vi.fn()));
    await act(async () => {
      await result.current.send("hi");
    });

    const assistantMsg = result.current.messages.find((m) => m.role === "assistant")!;
    expect(assistantMsg.error).toBe(true);
    expect(assistantMsg.text).toBe("Internal server error while processing your message.");
    expect(result.current.streamError).toBe("Internal server error while processing your message.");
  });

  it("surfaces a connection failure (thrown by streamChat) as an error on the assistant message", async () => {
    mockedStreamChat.mockRejectedValue(new Error("Network error"));

    const { result } = renderHook(() => useChat(null, vi.fn()));
    await act(async () => {
      await result.current.send("hi");
    });

    const assistantMsg = result.current.messages.find((m) => m.role === "assistant")!;
    expect(assistantMsg.error).toBe(true);
    expect(result.current.sending).toBe(false);
  });

  it("ignores an AbortError from stop() without setting streamError", async () => {
    mockedStreamChat.mockRejectedValue(new DOMException("aborted", "AbortError"));

    const { result } = renderHook(() => useChat(null, vi.fn()));
    await act(async () => {
      await result.current.send("hi");
    });

    expect(result.current.streamError).toBeNull();
  });

  it("does not send an empty or whitespace-only message", async () => {
    const { result } = renderHook(() => useChat(null, vi.fn()));
    await act(async () => {
      await result.current.send("   ");
    });

    expect(mockedStreamChat).not.toHaveBeenCalled();
    expect(result.current.messages).toHaveLength(0);
  });

  it("reset() clears messages, activity, and any error", async () => {
    scriptEvents([{ type: "error", data: { message: "boom" } }]);
    const { result } = renderHook(() => useChat(null, vi.fn()));
    await act(async () => {
      await result.current.send("hi");
    });
    expect(result.current.messages.length).toBeGreaterThan(0);

    act(() => {
      result.current.reset();
    });

    await waitFor(() => {
      expect(result.current.messages).toHaveLength(0);
      expect(result.current.activity).toHaveLength(0);
      expect(result.current.streamError).toBeNull();
    });
  });

  it("attaches document_created events to the finished assistant message", async () => {
    scriptEvents([
      { type: "text_delta", data: { text: "Done." } },
      { type: "document_created", data: { phase: "requirements", filename: "reqs.md" } },
      { type: "message_complete", data: { answer: "Done.", session_id: "prj_1" } },
    ]);

    const { result } = renderHook(() => useChat("prj_1", vi.fn()));
    await act(async () => {
      await result.current.send("run requirements");
    });

    const assistantMsg = result.current.messages.find((m) => m.role === "assistant")!;
    expect(assistantMsg.documents).toEqual([
      { phase: "requirements", label: "requirements", filename: "reqs.md" },
    ]);
  });
});
