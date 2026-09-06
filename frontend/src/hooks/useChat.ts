import { useCallback, useRef, useState } from "react";
import { api } from "../api/client";
import type { ChatMessage, ChatStreamEvent, DocumentRef } from "../types";

export interface AgentActivityStep {
  key: string;
  label: string;
  done: boolean;
}

function newId(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function useChat(sessionId: string | null, onSessionCreated: (id: string) => void) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activity, setActivity] = useState<AgentActivityStep[]>([]);
  const [sending, setSending] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    setMessages([]);
    setActivity([]);
    setStreamError(null);
  }, []);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || sending) return;

      setStreamError(null);
      const userMessage: ChatMessage = {
        id: newId(),
        role: "user",
        text: trimmed,
        createdAt: Date.now(),
      };
      const assistantId = newId();
      const assistantMessage: ChatMessage = {
        id: assistantId,
        role: "assistant",
        text: "",
        createdAt: Date.now(),
        isStreaming: true,
      };
      setMessages((prev) => [...prev, userMessage, assistantMessage]);
      setActivity([]);
      setSending(true);

      const controller = new AbortController();
      abortRef.current = controller;
      const documents: DocumentRef[] = [];

      const applyDelta = (chunk: string) => {
        setMessages((prev) =>
          prev.map((m) => (m.id === assistantId ? { ...m, text: m.text + chunk } : m)),
        );
      };

      const pushActivity = (key: string, label: string) => {
        setActivity((prev) => {
          const existing = prev.find((s) => s.key === key);
          if (existing) return prev.map((s) => (s.key === key ? { ...s, label } : s));
          return [...prev, { key, label, done: false }];
        });
      };

      const completeActivity = (key: string) => {
        setActivity((prev) => prev.map((s) => (s.key === key ? { ...s, done: true } : s)));
      };

      const handleEvent = (event: ChatStreamEvent) => {
        switch (event.type) {
          case "message_start":
            break;
          case "agent_started":
            pushActivity(String(event.data.agent ?? "agent"), String(event.data.message ?? "Working"));
            break;
          case "agent_progress":
            pushActivity(String(event.data.agent ?? "agent"), String(event.data.message ?? "Working"));
            break;
          case "tool_started":
            pushActivity(String(event.data.tool ?? "tool"), String(event.data.message ?? "Working"));
            break;
          case "tool_completed":
            completeActivity(String(event.data.tool ?? "tool"));
            break;
          case "text_delta":
            applyDelta(String(event.data.text ?? ""));
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
            if (newSessionId && !sessionId) onSessionCreated(newSessionId);
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, isStreaming: false, documents: documents.length ? documents : undefined }
                  : m,
              ),
            );
            break;
          }
          case "error":
            setStreamError(String(event.data.message ?? "Something went wrong."));
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? {
                      ...m,
                      isStreaming: false,
                      error: true,
                      text: m.text || String(event.data.message ?? "Something went wrong."),
                    }
                  : m,
              ),
            );
            break;
        }
      };

      try {
        await api.streamChat(trimmed, sessionId, handleEvent, controller.signal);
      } catch (err) {
        if (!(err instanceof DOMException && err.name === "AbortError")) {
          const message = err instanceof Error ? err.message : "Connection lost.";
          setStreamError(message);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, isStreaming: false, error: true, text: m.text || message } : m,
            ),
          );
        }
      } finally {
        setSending(false);
        abortRef.current = null;
      }
    },
    [sessionId, sending, onSessionCreated],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { messages, activity, sending, streamError, send, stop, reset };
}
