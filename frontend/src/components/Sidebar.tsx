import { useMemo, useState } from "react";
import { Archive, LogOut, Pencil, Plus, Search } from "lucide-react";
import type { ProjectSummary } from "../types";
import { useAuth } from "../context/AuthContext";

export function Sidebar({
  projects,
  activeSessionId,
  onSelect,
  onNewProject,
  onRename,
  onArchive,
}: {
  projects: ProjectSummary[];
  activeSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onNewProject: () => void;
  onRename: (sessionId: string, currentName: string) => void;
  onArchive: (sessionId: string) => void;
}) {
  const { user, logout } = useAuth();
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    if (!query.trim()) return projects;
    const q = query.toLowerCase();
    return projects.filter((p) => p.project_name.toLowerCase().includes(q));
  }, [projects, query]);

  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-r border-border bg-surface">
      <div className="border-b border-border p-4">
        <h1 className="font-display text-lg text-ink">ERP Consultant AI</h1>
        <button
          onClick={onNewProject}
          className="mt-3 flex w-full items-center justify-center gap-2 rounded-md bg-accent py-2 text-sm font-medium text-white transition-colors hover:bg-accent-strong"
        >
          <Plus size={15} />
          New project
        </button>
      </div>

      <div className="border-b border-border p-3">
        <div className="flex items-center gap-2 rounded-md border border-border bg-paper px-2.5 py-1.5">
          <Search size={14} className="shrink-0 text-ink-faint" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search projects"
            className="w-full bg-transparent text-sm text-ink outline-none placeholder:text-ink-faint"
          />
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto p-2">
        {filtered.length === 0 && (
          <p className="px-2 py-4 text-center text-sm text-ink-faint">
            {projects.length === 0 ? "No projects yet." : "No matches."}
          </p>
        )}
        <ul className="space-y-0.5">
          {filtered.map((project) => (
            <li key={project.session_id} className="group relative">
              <button
                onClick={() => onSelect(project.session_id)}
                className={`w-full rounded-md px-3 py-2 text-left text-sm transition-colors ${
                  project.session_id === activeSessionId
                    ? "bg-accent-soft text-accent-strong"
                    : "text-ink hover:bg-paper"
                }`}
              >
                <span className="block truncate pr-12 font-medium">{project.project_name}</span>
                <span className="block truncate pr-12 text-xs text-ink-faint">
                  {project.module} · {project.current_phase.replace(/_/g, " ")}
                </span>
              </button>
              <div className="absolute right-1.5 top-1.5 hidden gap-1 group-hover:flex">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onRename(project.session_id, project.project_name);
                  }}
                  title="Rename"
                  className="rounded-sm p-1 text-ink-faint hover:bg-surface hover:text-ink"
                >
                  <Pencil size={13} />
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onArchive(project.session_id);
                  }}
                  title="Archive"
                  className="rounded-sm p-1 text-ink-faint hover:bg-surface hover:text-danger"
                >
                  <Archive size={13} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      </nav>

      <div className="flex items-center justify-between border-t border-border p-3">
        <span className="truncate text-xs text-ink-muted">{user?.email}</span>
        <button
          onClick={logout}
          title="Log out"
          className="rounded-sm p-1.5 text-ink-faint hover:bg-paper hover:text-ink"
        >
          <LogOut size={15} />
        </button>
      </div>
    </aside>
  );
}
