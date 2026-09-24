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
  // Load errors are stored alongside the session they belong to, so a
  // stale error from a previous session is never surfaced for the
  // current one. This is what allows us to avoid a synchronous
  // setLoadError inside the effect.
  const [errorState, setErrorState] = useState<
    { forSession: string; message: string } | null
  >(null);

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
  const { loadHistory } = chat;

  useEffect(() => {
    if (!sessionId) {
      return;
    }
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
              turnState:
                m.role === "assistant" ? { status: "complete" } : undefined,
            }),
          ),
        );
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.kind === "aborted") return;
        setErrorState({
          forSession: sessionId,
          message:
            err instanceof Error ? err.message : "Could not load messages.",
        });
      });
    return () => controller.abort();
  }, [sessionId, loadHistory]);

  const loadError =
    sessionId && errorState?.forSession === sessionId
      ? errorState.message
      : null;

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