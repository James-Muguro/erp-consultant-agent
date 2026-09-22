import { useCallback, useEffect, useMemo, useState } from "react";
import { Menu } from "lucide-react";
import { Outlet, useNavigate, useParams } from "react-router-dom";
import { Sidebar } from "../components/Sidebar";
import { NewProjectModal } from "../components/NewProjectModal";
import { useConfirm } from "../context/ConfirmContext";
import { api } from "../api/client";
import type { ProjectSummary } from "../types";

export function AppLayout() {
  const navigate = useNavigate();
  const confirm = useConfirm();
  const { sessionId } = useParams<{ sessionId?: string }>();

  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [projectsError, setProjectsError] = useState<string | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [showNewProject, setShowNewProject] = useState(false);

  const refreshProjects = useCallback(async () => {
    setProjectsError(null);
    try {
      const res = await api.listProjects(showArchived);
      setProjects(res.projects);
    } catch (err) {
      setProjectsError(
        err instanceof Error ? err.message : "Could not load projects.",
      );
    }
  }, [showArchived]);

  useEffect(() => {
    let cancelled = false;
    setLoadingProjects(true);
    refreshProjects().finally(() => {
      if (!cancelled) setLoadingProjects(false);
    });
    return () => {
      cancelled = true;
    };
  }, [refreshProjects]);

  const activeProject = useMemo(
    () =>
      sessionId
        ? projects.find((p) => p.session_id === sessionId) ?? null
        : null,
    [projects, sessionId],
  );

  const handleSelectProject = useCallback(
    (id: string) => {
      navigate(`/p/${id}`);
      setSidebarOpen(false);
    },
    [navigate],
  );

  const handleNewChat = useCallback(() => {
    navigate("/chat");
    setSidebarOpen(false);
  }, [navigate]);

  const handleNewProject = useCallback(() => {
    setShowNewProject(true);
    setSidebarOpen(false);
  }, []);

  const handleOpenSettings = useCallback(() => {
    navigate("/settings");
    setSidebarOpen(false);
  }, [navigate]);

  const handleCreateProject = useCallback(
    async (name: string, module: string, erpSystem: string) => {
      const { session_id, next_action } = await api.startProject(
        name,
        module,
        erpSystem || undefined,
      );
      await refreshProjects();
      setShowNewProject(false);
      navigate(`/p/${session_id}/chat`, {
        state: { nextAction: next_action ?? null },
      });
    },
    [navigate, refreshProjects],
  );

  const handleRenameProject = useCallback(
    async (id: string, newName: string) => {
      await api.renameProject(id, newName);
      await refreshProjects();
    },
    [refreshProjects],
  );

  // The API call runs inside `onConfirm` so a failure (409 on already
  // archived, 401 on expired session, network) keeps the dialog open
  // with the error inline. This matches the delete handler below. The
  // previous version of this handler called `confirm()` and then did
  // nothing — the archive request was never sent.
  const handleArchiveProject = useCallback(
    async (id: string) => {
      const project = projects.find((p) => p.session_id === id);
      const label = project?.project_name ?? "this project";
      const confirmed = await confirm({
        title: `Archive "${label}"?`,
        description:
          "You can restore it later by showing archived projects in the sidebar.",
        confirmLabel: "Archive",
        onConfirm: async () => {
          await api.archiveProject(id);
        },
      });
      if (!confirmed) return;
      if (sessionId === id) navigate("/");
      await refreshProjects();
    },
    [confirm, navigate, projects, refreshProjects, sessionId],
  );

  const handleDeleteProject = useCallback(
    async (id: string) => {
      const project = projects.find((p) => p.session_id === id);
      const label = project?.project_name ?? "this project";
      const confirmed = await confirm({
        title: `Permanently delete "${label}"?`,
        description:
          "This removes the project, every conversation in it, and every generated or uploaded document. This cannot be undone.",
        confirmLabel: "Delete permanently",
        variant: "danger",
        onConfirm: async () => {
          await api.deleteProject(id);
        },
      });
      if (!confirmed) return;
      if (sessionId === id) navigate("/");
      await refreshProjects();
    },
    [confirm, navigate, projects, refreshProjects, sessionId],
  );

  return (
    <div className="flex h-screen bg-paper">
      <Sidebar
        projects={projects}
        activeSessionId={sessionId ?? null}
        onSelect={handleSelectProject}
        onNewChat={handleNewChat}
        onNewProject={handleNewProject}
        onRename={handleRenameProject}
        onArchive={handleArchiveProject}
        onDelete={handleDeleteProject}
        onOpenSettings={handleOpenSettings}
        showArchived={showArchived}
        onToggleArchived={() => setShowArchived((v) => !v)}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="safe-top flex shrink-0 items-center gap-2 border-b border-border bg-surface px-3 pb-2.5 md:hidden">
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

        {loadingProjects ? (
          <div className="flex flex-1 items-center justify-center text-sm text-ink-faint">
            Loading your projects…
          </div>
        ) : projectsError ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
            <p className="text-sm text-danger">{projectsError}</p>
            <button
              onClick={() => refreshProjects()}
              className="rounded-md border border-border-strong px-3 py-1.5 text-xs text-ink-muted hover:border-accent hover:text-accent"
            >
              Retry
            </button>
          </div>
        ) : (
          <main className="flex min-h-0 min-w-0 flex-1 flex-col">
            <Outlet />
          </main>
        )}
      </div>

      {showNewProject && (
        <NewProjectModal
          onClose={() => setShowNewProject(false)}
          onCreate={handleCreateProject}
        />
      )}
    </div>
  );
}