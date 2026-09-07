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

  function selectProject(sessionId: string) {
    setActiveSessionId(sessionId);
    chat.reset();
  }

  function newChat() {
    setActiveSessionId(null);
    chat.reset();
  }

  async function createProject(name: string, erpSystem: string) {
    const { session_id } = await api.startProject(name, "General", erpSystem || undefined);
    await refreshProjects();
    setActiveSessionId(session_id);
    chat.reset();
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