import { useCallback, useEffect, useMemo, useState } from "react";
import { Menu } from "lucide-react";
import { Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { Sidebar } from "../components/Sidebar";
import { NewProjectModal } from "../components/NewProjectModal";
import { useConfirm } from "../context/useConfirm";
import { api } from "../api/client";
import { ErrorBoundary } from "./ErrorBoundary";
import type { ProjectSummary } from "../types";

function RouteContentError({
  error,
  onRetry,
}: {
  error: Error;
  onRetry: () => void;
}) {
  return (
    <div className="flex flex-1 items-center justify-center px-6 py-12">
      <div className="w-full max-w-md rounded-md border border-border bg-surface p-6 text-center">
        <h2 className="font-display text-lg text-ink">
          Something went wrong in this view
        </h2>
        <p className="mt-2 text-sm text-ink-muted">
          This section couldn't be displayed. Your work is saved on the
          server.
        </p>
        {error.message && (
          <p className="mt-3 break-words rounded-md bg-danger-soft px-3 py-2 text-xs text-danger">
            {error.message}
          </p>
        )}
        <button
          type="button"
          onClick={onRetry}
          className="mt-4 rounded-md bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-strong"
        >
          Try again
        </button>
      </div>
    </div>
  );
}

export function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const confirm = useConfirm();
  const { sessionId } = useParams<{ sessionId?: string }>();

  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [projectsError, setProjectsError] = useState<string | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [showNewProject, setShowNewProject] = useState(false);

  // Load (or reload) the project list. State updates happen only after
  // the awaited call, so this can be invoked from the mount effect
  // without triggering react/set-state-in-effect.
  const refreshProjects = useCallback(async () => {
    try {
      const res = await api.listProjects(showArchived);
      setProjects(res.projects);
      setProjectsError(null);
    } catch (err) {
      setProjectsError(
        err instanceof Error ? err.message : "Could not load projects.",
      );
    }
  }, [showArchived]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await api.listProjects(showArchived);
        if (cancelled) return;
        setProjects(res.projects);
        setProjectsError(null);
      } catch (err) {
        if (cancelled) return;
        setProjectsError(
          err instanceof Error ? err.message : "Could not load projects.",
        );
      } finally {
        if (!cancelled) setLoadingProjects(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [showArchived]);

  const handleToggleArchived = useCallback(() => {
    setLoadingProjects(true);
    setShowArchived((v) => !v);
  }, []);

  const handleRetryProjects = useCallback(() => {
    setLoadingProjects(true);
    void refreshProjects().finally(() => {
      setLoadingProjects(false);
    });
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
    <div className="app-viewport flex bg-paper">
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
        onToggleArchived={handleToggleArchived}
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
              onClick={handleRetryProjects}
              className="rounded-md border border-border-strong px-3 py-1.5 text-xs text-ink-muted hover:border-accent hover:text-accent"
            >
              Retry
            </button>
          </div>
        ) : (
          <main className="flex min-h-0 min-w-0 flex-1 flex-col">
            <ErrorBoundary
              key={location.pathname}
              fallback={(error, reset) => (
                <RouteContentError error={error} onRetry={reset} />
              )}
            >
              <Outlet />
            </ErrorBoundary>
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