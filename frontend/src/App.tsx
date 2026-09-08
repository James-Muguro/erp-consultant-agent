import { useCallback, useEffect, useState } from "react";
import { useAuth } from "./context/AuthContext";
import { LoginPage } from "./pages/LoginPage";
import { Sidebar } from "./components/Sidebar";
import { ChatPanel } from "./components/ChatPanel";
import { NewProjectModal } from "./components/NewProjectModal";
import { useChat } from "./hooks/useChat";
import { api } from "./api/client";
import type { ProjectSummary } from "./types";

function ChatApp() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [showNewProject, setShowNewProject] = useState(false);
  const [loadingProjects, setLoadingProjects] = useState(true);

  const refreshProjects = useCallback(async () => {
    const { projects } = await api.listProjects();
    setProjects(projects);
  }, []);

  useEffect(() => {
    refreshProjects().finally(() => setLoadingProjects(false));
  }, [refreshProjects]);

  const handleSessionCreated = useCallback(
    (id: string) => {
      setActiveSessionId(id);
      refreshProjects();
    },
    [refreshProjects],
  );

  const chat = useChat(activeSessionId, handleSessionCreated);

  async function selectProject(sessionId: string) {
    setActiveSessionId(sessionId);
    chat.reset();
    const { messages } = await api.getMessages(sessionId);
    chat.loadHistory(
      messages.map((m, i) => ({
        id: `${sessionId}-${i}`,
        role: m.role === "assistant" ? "assistant" : "user",
        text: m.content,
        createdAt: new Date(m.timestamp).getTime(),
      })),
    );
  }
  function newChat() {
    setActiveSessionId(null);
    chat.reset();
  }

  async function createProject(name: string, erpSystem: string) {
    const { session_id, next_action } = await api.startProject(name, "General", erpSystem || undefined);
    await refreshProjects();
    setActiveSessionId(session_id);
    chat.reset();
    if (next_action) {
      chat.loadHistory([
        {
          id: `${session_id}-welcome`,
          role: "assistant",
          text: `"${name}" is ready. Let's get started.`,
          createdAt: Date.now(),
          nextAction: next_action,
        },
      ]);
    }
    setShowNewProject(false);
  }

async function renameProject(sessionId: string, newName: string) {
  await api.renameProject(sessionId, newName);
  await refreshProjects();
}

  async function archiveProject(sessionId: string) {
    if (!window.confirm("Archive this project? You can still access it later if needed.")) return;
    await api.archiveProject(sessionId);
    if (sessionId === activeSessionId) {
      setActiveSessionId(null);
      chat.reset();
    }
    await refreshProjects();
  }

  async function deleteProject(sessionId: string) {
    if (!window.confirm("Permanently delete this chat? This cannot be undone.")) return;
    await api.deleteProject(sessionId);
    if (sessionId === activeSessionId) {
      setActiveSessionId(null);
      chat.reset();
    }
    await refreshProjects();
  }

  return (
    <div className="flex h-screen bg-paper">
      <Sidebar
        projects={projects}
        activeSessionId={activeSessionId}
        onSelect={selectProject}
        onNewChat={newChat}
        onNewProject={() => setShowNewProject(true)}
        onRename={renameProject}
        onArchive={archiveProject}
        onDelete={deleteProject}
        />
      <main className="flex flex-1 flex-col">
        {loadingProjects ? (
          <div className="flex flex-1 items-center justify-center text-sm text-ink-faint">
            Loading your projects…
          </div>
        ) : (
          <ChatPanel
            sessionId={activeSessionId}
            messages={chat.messages}
            activity={chat.activity}
            sending={chat.sending}
            streamError={chat.streamError}
            onSend={chat.send}
            onStop={chat.stop}
          />
        )}
      </main>

      {showNewProject && (
        <NewProjectModal onClose={() => setShowNewProject(false)} onCreate={createProject} />
      )}
    </div>
  );
}

export default function App() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-paper text-sm text-ink-faint">
        Loading…
      </div>
    );
  }

  return user ? <ChatApp /> : <LoginPage />;
}