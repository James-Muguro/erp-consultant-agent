import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { useChat } from "./useChat";
import type { ChatStreamEvent } from "../types";
import { api, ApiError } from "../api/client";

// Preserve the real ApiError class (useChat branches on `instanceof
// ApiError` for abort/retryability classification) and mock only the API
// surface. Replacing the whole module would make `err instanceof ApiError`
// throw at runtime, which the type checker would not catch.
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>(
    "../api/client",
  );
  return {
    ...actual,
    api: { streamChat: vi.fn() },
  };
});

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
      () =>
        new Promise((resolve) => {
          resolveStream = () => resolve(undefined);
        }),
    );

    const { result } = renderHook(() => useChat(null, vi.fn()));
    act(() => {
      result.current.send("hello there");
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0]).toMatchObject({
      role: "user",
      text: "hello there",
    });
    expect(result.current.messages[1]).toMatchObject({
      role: "assistant",
      turnState: { status: "streaming" },
    });
    expect(result.current.sending).toBe(true);

    await act(async () => {
      resolveStream();
    });
  });

  it("accumulates text_delta chunks and finalizes on message_complete", async () => {
    scriptEvents([
      { type: "message_start", data: {} },
      { type: "text_delta", data: { text: "Hello, " } },
      { type: "text_delta", data: { text: "world." } },
      { type: "workflow_completed", data: {} },
      {
        type: "message_complete",
        data: { answer: "Hello, world.", session_id: null },
      },
    ]);

    const { result } = renderHook(() => useChat(null, vi.fn()));
    await act(async () => {
      await result.current.send("hi");
    });

    const assistantMsg = result.current.messages.find(
      (m) => m.role === "assistant",
    )!;
    expect(assistantMsg.text).toBe("Hello, world.");
    expect(assistantMsg.turnState?.status).toBe("complete");
    expect(result.current.sending).toBe(false);
    // Activity is a live indicator: it exists during the turn and is
    // cleared in the finally block, so a completed turn leaves no
    // in-progress steps behind.
    expect(result.current.activity).toHaveLength(0);
  });

  it("marks a tool step done mid-turn on tool_completed", async () => {
    // The activity list is a live indicator; the previous version of this
    // test asserted on it after the turn had ended, which no longer works
    // because activity is cleared at end-of-turn. Hold the stream open so
    // the mid-turn state can be observed.
    let resolveStream: () => void = () => {};
    mockedStreamChat.mockImplementation(async (_msg, _sid, onEvent) => {
      onEvent({
        type: "tool_started",
        data: { tool: "info_retriever", message: "Searching" },
      });
      onEvent({ type: "tool_completed", data: { tool: "info_retriever" } });
      await new Promise<void>((resolve) => {
        resolveStream = resolve;
      });
    });

    const { result } = renderHook(() => useChat(null, vi.fn()));
    let sendPromise: Promise<void>;
    act(() => {
      sendPromise = result.current.send("hi");
    });

    // Mid-turn: the tool step should be marked done.
    await waitFor(() => {
      const step = result.current.activity.find(
        (s) => s.key === "info_retriever",
      );
      expect(step?.done).toBe(true);
    });

    // Release the stream. After the turn ends, activity is cleared.
    await act(async () => {
      resolveStream();
      await sendPromise!;
    });
    expect(result.current.activity).toHaveLength(0);
  });

  it("calls onSessionCreated when message_complete carries a new session_id and none was set", async () => {
    scriptEvents([
      { type: "message_start", data: {} },
      { type: "text_delta", data: { text: "Started!" } },
      {
        type: "message_complete",
        data: { answer: "Started!", session_id: "prj_new_123" },
      },
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
      {
        type: "message_complete",
        data: { answer: "ok", session_id: "prj_existing" },
      },
    ]);

    const onSessionCreated = vi.fn();
    const { result } = renderHook(() =>
      useChat("prj_existing", onSessionCreated),
    );
    await act(async () => {
      await result.current.send("continue");
    });

    expect(onSessionCreated).not.toHaveBeenCalled();
  });

  it("marks the assistant turn failed on an error event", async () => {
    scriptEvents([
      { type: "message_start", data: {} },
      {
        type: "error",
        data: {
          message: "Internal server error while processing your message.",
        },
      },
    ]);

    const { result } = renderHook(() => useChat(null, vi.fn()));
    await act(async () => {
      await result.current.send("hi");
    });

    const assistantMsg = result.current.messages.find(
      (m) => m.role === "assistant",
    )!;
    expect(assistantMsg.turnState).toEqual({
      status: "failed",
      error: "Internal server error while processing your message.",
      retryable: true,
    });
    // The hook stores the error on `turnState.error` and does not copy it
    // into `text`. MessageBubble derives the visible bubble content from
    // `text || turnState.error`, so there is one source of truth for the
    // error string rather than two that can drift. If partial text
    // arrived before the error, the partial text is preserved and the
    // error is only visible via `turnState`.
    expect(assistantMsg.text).toBe("");
  });

  it("surfaces a connection failure as a retryable failed turn", async () => {
    mockedStreamChat.mockRejectedValue(new Error("Network error"));

    const { result } = renderHook(() => useChat(null, vi.fn()));
    await act(async () => {
      await result.current.send("hi");
    });

    const assistantMsg = result.current.messages.find(
      (m) => m.role === "assistant",
    )!;
    expect(assistantMsg.turnState).toEqual({
      status: "failed",
      error: "Network error",
      retryable: true,
    });
    expect(result.current.sending).toBe(false);
  });

  it("marks the assistant turn aborted (not failed) when the stream aborts", async () => {
    mockedStreamChat.mockRejectedValue(
      new DOMException("aborted", "AbortError"),
    );

    const { result } = renderHook(() => useChat(null, vi.fn()));
    await act(async () => {
      await result.current.send("hi");
    });

    const assistantMsg = result.current.messages.find(
      (m) => m.role === "assistant",
    )!;
    expect(assistantMsg.turnState?.status).toBe("aborted");
    expect(result.current.sending).toBe(false);
  });

  it("does not send an empty or whitespace-only message", async () => {
    const { result } = renderHook(() => useChat(null, vi.fn()));
    await act(async () => {
      await result.current.send("   ");
    });

    expect(mockedStreamChat).not.toHaveBeenCalled();
    expect(result.current.messages).toHaveLength(0);
  });

  it("reset() clears messages and activity", async () => {
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
    });
  });

  it("loadHistory marks historical assistant messages complete", () => {
    // Historical turns loaded from the server are, by definition,
    // complete. loadHistory stamps that explicitly so no rendering code
    // has to interpret "turnState missing" as "complete".
    const { result } = renderHook(() => useChat("prj_1", vi.fn()));

    act(() => {
      result.current.loadHistory([
        { id: "u1", role: "user", text: "hi", createdAt: 1 },
        { id: "a1", role: "assistant", text: "hello", createdAt: 2 },
      ]);
    });

    const [userMsg, assistantMsg] = result.current.messages;
    expect(userMsg.turnState).toBeUndefined();
    expect(assistantMsg.turnState).toEqual({ status: "complete" });
  });

  it("attaches document_created events to the finished assistant message", async () => {
    scriptEvents([
      { type: "text_delta", data: { text: "Done." } },
      {
        type: "document_created",
        data: { phase: "requirements", filename: "reqs.md" },
      },
      {
        type: "message_complete",
        data: { answer: "Done.", session_id: "prj_1" },
      },
    ]);

    const { result } = renderHook(() => useChat("prj_1", vi.fn()));
    await act(async () => {
      await result.current.send("run requirements");
    });

    const assistantMsg = result.current.messages.find(
      (m) => m.role === "assistant",
    )!;
    expect(assistantMsg.documents).toEqual([
      {
        phase: "requirements",
        label: "requirements",
        filename: "reqs.md",
      },
    ]);
  });

  it("retry replaces the failed assistant turn and reuses the original user message", async () => {
    // First attempt: connection failure.
    mockedStreamChat.mockRejectedValueOnce(new Error("Network error"));

    const { result } = renderHook(() => useChat("prj_1", vi.fn()));
    await act(async () => {
      await result.current.send("hello");
    });

    const failedMsg = result.current.messages.find(
      (m) => m.role === "assistant",
    )!;
    expect(failedMsg.turnState).toMatchObject({
      status: "failed",
      retryable: true,
    });

    // Second attempt: successful stream, triggered by retry().
    scriptEvents([
      { type: "text_delta", data: { text: "Hi there." } },
      {
        type: "message_complete",
        data: { answer: "Hi there.", session_id: "prj_1" },
      },
    ]);
    await act(async () => {
      await result.current.retry(failedMsg.id);
    });

    // Retry reuses the user message rather than appending a second one.
    expect(result.current.messages).toHaveLength(2);
    const [userMsg, assistantMsg] = result.current.messages;
    expect(userMsg.role).toBe("user");
    expect(userMsg.text).toBe("hello");
    expect(assistantMsg.role).toBe("assistant");
    expect(assistantMsg.turnState?.status).toBe("complete");
    expect(assistantMsg.text).toBe("Hi there.");

    // streamChat was called twice, and the second call carried the same
    // message text and preferWeb value as the original.
    expect(mockedStreamChat).toHaveBeenCalledTimes(2);
    expect(mockedStreamChat).toHaveBeenLastCalledWith(
      "hello",
      "prj_1",
      expect.any(Function),
      expect.any(AbortSignal),
      undefined,
      false,
    );
  });

  it("retry is a no-op for a non-retryable failure", async () => {
    // A 422 is a validation error: retrying would just fail the same way.
    mockedStreamChat.mockRejectedValueOnce(
      new ApiError({
        status: 422,
        kind: "validation",
        message: "Bad input.",
      }),
    );

    const { result } = renderHook(() => useChat("prj_1", vi.fn()));
    await act(async () => {
      await result.current.send("hello");
    });

    const failedMsg = result.current.messages.find(
      (m) => m.role === "assistant",
    )!;
    expect(failedMsg.turnState).toMatchObject({
      status: "failed",
      retryable: false,
    });

    // Retry must not call streamChat again for a non-retryable failure.
    await act(async () => {
      await result.current.retry(failedMsg.id);
    });
    expect(mockedStreamChat).toHaveBeenCalledTimes(1);
  });

  it("passes preferWeb through to streamChat when enabled", async () => {
    scriptEvents([
      {
        type: "message_complete",
        data: { answer: "ok", session_id: "prj_1" },
      },
    ]);

    const { result } = renderHook(() => useChat("prj_1", vi.fn()));
    act(() => {
      result.current.setPreferWeb(true);
    });
    await act(async () => {
      await result.current.send("hi");
    });

    expect(mockedStreamChat).toHaveBeenLastCalledWith(
      "hi",
      "prj_1",
      expect.any(Function),
      expect.any(AbortSignal),
      undefined,
      true,
    );
  });
});