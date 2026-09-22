import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import type {
  ChatMessage,
  ChatStreamEvent,
  DocumentRef,
  NextAction,
  TurnState,
} from "../types";

export interface AgentActivityStep {
  key: string;
  label: string;
  done: boolean;
}

function newId(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

/**
 * True when the error represents a caller-initiated abort. The API client
 * converts a fetch AbortError into ApiError({kind: "aborted"}), but this
 * hook also accepts the raw DOMException so it keeps working if either
 * side evolves.
 */
function isAbort(err: unknown): boolean {
  if (err instanceof ApiError) return err.kind === "aborted";
  if (err instanceof DOMException && err.name === "AbortError") return true;
  if (err instanceof Error && err.name === "AbortError") return true;
  return false;
}

/**
 * Whether retrying the failed turn is plausibly useful.
 *
 *   - auth (401/403): user needs to sign in again; retry won't help.
 *   - validation (400/413/422): the request was wrong; retry won't help.
 *   - not_found (404): the resource is gone; retry won't help.
 *   - conflict (409): state disagreement; retry won't help.
 *   - rate_limit (429): retry after cooldown; likely to succeed.
 *   - server (5xx): possibly transient; likely to succeed.
 *   - network: definitely transient; likely to succeed.
 *   - aborted: user chose to stop; retry is unnecessary.
 */
function isRetryable(err: unknown): boolean {
  if (!(err instanceof ApiError)) return true;
  switch (err.kind) {
    case "auth":
    case "validation":
    case "not_found":
    case "conflict":
    case "aborted":
      return false;
    case "rate_limit":
    case "server":
    case "network":
    case "unknown":
      return true;
    default:
      return true;
  }
}

export function useChat(
  sessionId: string | null,
  onSessionCreated: (id: string) => void,
) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activity, setActivity] = useState<AgentActivityStep[]>([]);
  const [sending, setSending] = useState(false);
  const [preferWeb, setPreferWeb] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  // Latest values read inside stable callbacks without adding deps.
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;
  const messagesRef = useRef(messages);
  messagesRef.current = messages;

  // Abort any in-flight stream when the hook unmounts. In the routed app
  // this fires when the user navigates away from a chat mid-turn (the
  // ChatRouteInner remounts with a new key on session change). The abort
  // surfaces as ApiError({kind: "aborted"}) in the turn's catch and is
  // classified as an abort, not a failure, so nothing user-visible is
  // shown for a stream that was intentionally discarded.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, []);

  const loadHistory = useCallback((history: ChatMessage[]) => {
    // Historical turns are, by definition, complete. Attaching an
    // explicit `turnState` here keeps downstream rendering uniform -
    // every assistant message has a turn state and there is no
    // "missing means complete" special case to maintain.
    setMessages(
      history.map((m) =>
        m.role === "assistant" && !m.turnState
          ? { ...m, turnState: { status: "complete" as const } }
          : m,
      ),
    );
    setActivity([]);
  }, []);

  const reset = useCallback(() => {
    setMessages([]);
    setActivity([]);
  }, []);

  /**
   * Core streaming routine. Assumes an assistant message with id
   * `assistantId` has already been inserted into `messages`; this
   * function only updates it in place. Shared by `send` and `retry`.
   */
  const runTurn = useCallback(
    async ({
      assistantId,
      text,
      agentHint,
      preferWeb: preferWebForTurn,
    }: {
      assistantId: string;
      text: string;
      agentHint?: string;
      preferWeb: boolean;
    }) => {
      setActivity([]);
      setSending(true);
      const controller = new AbortController();
      abortRef.current = controller;
      const documents: DocumentRef[] = [];
      const sessionAtStart = sessionIdRef.current;

      const updateAssistant = (patch: Partial<ChatMessage>) => {
        setMessages((prev) =>
          prev.map((m) => (m.id === assistantId ? { ...m, ...patch } : m)),
        );
      };
      const setTurnState = (state: TurnState) => updateAssistant({ turnState: state });

      const pushActivity = (key: string, label: string) => {
        setActivity((prev) => {
          const existing = prev.find((s) => s.key === key);
          if (existing) return prev.map((s) => (s.key === key ? { ...s, label } : s));
          return [...prev, { key, label, done: false }];
        });
      };
      const completeActivity = (key: string) => {
        setActivity((prev) =>
          prev.map((s) => (s.key === key ? { ...s, done: true } : s)),
        );
      };

      const handleEvent = (event: ChatStreamEvent) => {
        switch (event.type) {
          case "message_start":
            break;
          case "agent_started":
          case "agent_progress":
            pushActivity(
              String(event.data.agent ?? "agent"),
              String(event.data.message ?? "Working"),
            );
            break;
          case "tool_started":
            pushActivity(
              String(event.data.tool ?? "tool"),
              String(event.data.message ?? "Working"),
            );
            break;
          case "tool_completed":
            completeActivity(String(event.data.tool ?? "tool"));
            break;
          case "text_delta":
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, text: m.text + String(event.data.text ?? "") }
                  : m,
              ),
            );
            break;
          case "document_created":
            documents.push({
              phase: String(event.data.phase ?? ""),
              label: String(event.data.label ?? event.data.phase ?? "Document"),
              filename: String(event.data.filename ?? ""),
            });
            break;
          case "workflow_completed":
            setActivity((prev) => prev.map((s) => ({ ...s, done: true })));
            break;
          case "message_complete": {
            const newSessionId = event.data.session_id as string | null | undefined;
            if (newSessionId && !sessionAtStart) onSessionCreated(newSessionId);
            const nextAction = (event.data.next_action ?? null) as NextAction | null;
            updateAssistant({
              turnState: { status: "complete" },
              documents: documents.length ? documents : undefined,
              nextAction,
            });
            break;
          }
          case "error":
            updateAssistant({
              turnState: {
                status: "failed",
                error: String(event.data.message ?? "Something went wrong."),
                retryable: true,
              },
            });
            break;
        }
      };

      try {
        await api.streamChat(
          text,
          sessionAtStart,
          handleEvent,
          controller.signal,
          agentHint,
          preferWebForTurn,
        );

        // If the stream ended without emitting `message_complete`, the
        // turn did not complete normally - most likely the connection
        // was dropped after the server stopped sending. Mark it failed
        // with retry available rather than leaving it stuck in
        // `streaming`.
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== assistantId) return m;
            if (m.turnState?.status !== "streaming") return m;
            return {
              ...m,
              turnState: {
                status: "failed",
                error: "The response ended unexpectedly. You can try again.",
                retryable: true,
              },
            };
          }),
        );
      } catch (err) {
        if (isAbort(err)) {
          setTurnState({ status: "aborted" });
        } else {
          const message =
            err instanceof Error ? err.message : "Connection lost.";
          setTurnState({
            status: "failed",
            error: message,
            retryable: isRetryable(err),
          });
        }
      } finally {
        setSending(false);
        abortRef.current = null;
        // The activity list is a live progress indicator. Once the turn
        // is over, it has served its purpose - keeping it around would
        // leave "in progress" steps on screen next to a failure.
        setActivity([]);
      }
    },
    [onSessionCreated],
  );

  const send = useCallback(
    async (text: string, agentHint?: string) => {
      const trimmed = text.trim();
      if (!trimmed || sending) return;

      const userMessage: ChatMessage = {
        id: newId(),
        role: "user",
        text: trimmed,
        createdAt: Date.now(),
        sendParams: { agentHint, preferWeb },
      };
      const assistantId = newId();
      const assistantMessage: ChatMessage = {
        id: assistantId,
        role: "assistant",
        text: "",
        createdAt: Date.now(),
        turnState: { status: "streaming" },
      };
      setMessages((prev) => [...prev, userMessage, assistantMessage]);

      await runTurn({
        assistantId,
        text: trimmed,
        agentHint,
        preferWeb,
      });
    },
    [sending, preferWeb, runTurn],
  );

  /**
   * Retry a failed assistant turn. The preceding user message is reused
   * rather than re-appended, so the client-side conversation matches
   * what the backend sees: on a turn that never received
   * `message_complete`, the backend did not persist the user message
   * either, so a single retried send corresponds to a single server-side
   * record.
   */
  const retry = useCallback(
    async (assistantMessageId: string) => {
      if (sending) return;
      const current = messagesRef.current;
      const idx = current.findIndex((m) => m.id === assistantMessageId);
      if (idx < 0) return;
      const failed = current[idx];
      if (
        failed.turnState?.status !== "failed" ||
        !failed.turnState.retryable
      ) {
        return;
      }

      // Walk back to the nearest preceding user message.
      let userIdx = idx - 1;
      while (userIdx >= 0 && current[userIdx].role !== "user") userIdx--;
      if (userIdx < 0) return;
      const userMessage = current[userIdx];

      const newAssistantId = newId();
      const newAssistant: ChatMessage = {
        id: newAssistantId,
        role: "assistant",
        text: "",
        createdAt: Date.now(),
        turnState: { status: "streaming" },
      };
      setMessages((prev) =>
        prev.map((m) => (m.id === assistantMessageId ? newAssistant : m)),
      );

      await runTurn({
        assistantId: newAssistantId,
        text: userMessage.text,
        agentHint: userMessage.sendParams?.agentHint,
        preferWeb: userMessage.sendParams?.preferWeb ?? preferWeb,
      });
    },
    [sending, preferWeb, runTurn],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return {
    messages,
    activity,
    sending,
    preferWeb,
    setPreferWeb,
    send,
    stop,
    retry,
    reset,
    loadHistory,
  };
}