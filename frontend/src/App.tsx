import { useCallback, useEffect, useState } from "react";
import { MessageSquare, LayoutGrid, Menu } from "lucide-react";
import { useAuth } from "./context/AuthContext";
import { LoginPage } from "./pages/LoginPage";
import { Sidebar } from "./components/Sidebar";
import { ChatPanel } from "./components/ChatPanel";
import { NewProjectModal } from "./components/NewProjectModal";
import { ProjectWorkspace } from "./components/workspace/ProjectWorkspace";
import { useChat } from "./hooks/useChat";
import { api } from "./api/client";
import type { ProjectSummary } from "./types";

type MainView = "workspace" | "chat";

function ChatApp() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [showNewProject, setShowNewProject] = useState(false);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [showArchived, setShowArchived] = useState(false);
  const [mainView, setMainView] = useState<MainView>("workspace");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const refreshProjects = useCallback(async () => {
    const { projects } = await api.listProjects(showArchived);
    setProjects(projects);
  }, [showArchived]);

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
    setMainView("workspace");
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
    setMainView("chat");
    chat.reset();
  }

  async function createProject(name: string, erpSystem: string) {
    const { session_id, next_action } = await api.startProject(name, "General", erpSystem || undefined);
    await refreshProjects();
    setActiveSessionId(session_id);
    setMainView("chat");
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

  const activeProject = projects.find((p) => p.session_id === activeSessionId);

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
        showArchived={showArchived}
        onToggleArchived={() => setShowArchived((current) => !current)}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        {/* Mobile-only header: the sidebar is an off-canvas drawer below
            the md breakpoint, so this is the only way to reach it there,
            and it keeps the current project visible without needing the
            drawer open. */}
        <header className="safe-top flex shrink-0 items-center gap-2 border-b border-border bg-surface px-3 py-2.5 md:hidden">
          <button
            onClick={() => setSidebarOpen(true)}
            aria-label="Open menu"
            className="rounded-md p-2 text-ink-muted hover:bg-paper hover:text-ink"
          >
            <Menu size={20} />
          </button>
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">
            {activeProject ? activeProject.project_name : "Tarzyna"}
          </span>
        </header>

        <main className="flex min-h-0 min-w-0 flex-1 flex-col">
          {loadingProjects ? (
            <div className="flex flex-1 items-center justify-center text-sm text-ink-faint">
              Loading your projects…
            </div>
          ) : (
            <>
              {activeSessionId && (
                <div className="flex shrink-0 gap-1 overflow-x-auto border-b border-border bg-surface px-3 py-2 md:px-4">
                  <button
                    onClick={() => setMainView("workspace")}
                    className={`flex shrink-0 items-center gap-1.5 rounded-md px-3 py-2 text-sm transition-colors md:py-1.5 ${
                      mainView === "workspace" ? "bg-accent-soft text-accent-strong" : "text-ink-muted hover:bg-paper"
                    }`}
                  >
                    <LayoutGrid size={14} />
                    Workspace
                  </button>
                  <button
                    onClick={() => setMainView("chat")}
                    className={`flex shrink-0 items-center gap-1.5 rounded-md px-3 py-2 text-sm transition-colors md:py-1.5 ${
                      mainView === "chat" ? "bg-accent-soft text-accent-strong" : "text-ink-muted hover:bg-paper"
                    }`}
                  >
                    <MessageSquare size={14} />
                    Chat
                  </button>
                </div>
              )}
              {activeSessionId && mainView === "workspace" ? (
                <ProjectWorkspace sessionId={activeSessionId} />
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
            </>
          )}
        </main>
      </div>

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