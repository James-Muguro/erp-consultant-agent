import { useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ChatPanel } from "../components/ChatPanel";
import { ProjectTabs } from "./ProjectTabs";
import { useChat } from "../hooks/useChat";
import { api, ApiError } from "../api/client";
import type { ChatMessage, NextAction } from "../types";

export function ChatRoute({ mode }: { mode: "project" | "adhoc" }) {
  const { sessionId: urlSessionId } = useParams<{ sessionId?: string }>();
  return (
    <ChatRouteInner
      key={urlSessionId ?? "new"}
      mode={mode}
      initialSessionId={urlSessionId ?? null}
    />
  );
}

function ChatRouteInner({
  mode,
  initialSessionId,
}: {
  mode: "project" | "adhoc";
  initialSessionId: string | null;
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const [sessionId, setSessionId] = useState<string | null>(initialSessionId);
  const [loadError, setLoadError] = useState<string | null>(null);

  const navState = location.state as { nextAction?: NextAction | null } | null;
  const projectStartAction = mode === "project" ? navState?.nextAction ?? null : null;

  const handleSessionCreated = useCallback(
    (id: string) => {
      setSessionId(id);
      if (mode === "adhoc") {
        navigate(`/chat/${id}`, { replace: true, state: location.state });
      }
    },
    [mode, navigate, location.state],
  );

  const chat = useChat(sessionId, handleSessionCreated);
  const { reset, loadHistory } = chat;

  useEffect(() => {
    if (!sessionId) {
      reset();
      return;
    }
    setLoadError(null);
    const controller = new AbortController();
    api
      .getMessages(sessionId, controller.signal)
      .then(({ messages }) => {
        loadHistory(
          messages.map(
            (m, i): ChatMessage => ({
              id: `${sessionId}-${i}`,
              role: m.role === "assistant" ? "assistant" : "user",
              text: m.content,
              createdAt: new Date(m.timestamp).getTime(),
              // History is always complete; loadHistory would set this
              // anyway, but being explicit here keeps the mapping
              // self-describing.
              turnState:
                m.role === "assistant" ? { status: "complete" } : undefined,
            }),
          ),
        );
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.kind === "aborted") return;
        setLoadError(
          err instanceof Error ? err.message : "Could not load messages.",
        );
      });
    return () => controller.abort();
  }, [sessionId, reset, loadHistory]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {mode === "project" && sessionId && <ProjectTabs sessionId={sessionId} />}
      {loadError ? (
        <div className="flex flex-1 items-center justify-center px-6">
          <p className="text-sm text-danger">{loadError}</p>
        </div>
      ) : (
        <ChatPanel
          sessionId={sessionId}
          messages={chat.messages}
          activity={chat.activity}
          sending={chat.sending}
          preferWeb={chat.preferWeb}
          projectStartAction={projectStartAction}
          onSend={chat.send}
          onStop={chat.stop}
          onRetry={chat.retry}
          onTogglePreferWeb={() => chat.setPreferWeb((v) => !v)}
        />
      )}
    </div>
  );
}