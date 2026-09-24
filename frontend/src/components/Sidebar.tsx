import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import {
  Archive,
  ChevronDown,
  LogOut,
  MessageSquarePlus,
  Pencil,
  Plus,
  Search,
  Settings as SettingsIcon,
  Trash2,
  X,
} from "lucide-react";
import type { ProjectSummary } from "../types";
import { useAuth } from "../context/useAuth";
import { Avatar } from "./Avatar";

export function Sidebar({
  projects,
  activeSessionId,
  onSelect,
  onNewChat,
  onNewProject,
  onRename,
  onArchive,
  onDelete,
  onOpenSettings,
  showArchived,
  onToggleArchived,
  isOpen,
  onClose,
}: {
  projects: ProjectSummary[];
  activeSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onNewChat: () => void;
  onNewProject: () => void;
  onRename: (sessionId: string, newName: string) => void;
  onArchive: (sessionId: string) => void;
  onDelete: (sessionId: string) => void;
  onOpenSettings: () => void;
  showArchived: boolean;
  onToggleArchived: () => void;
  isOpen: boolean;
  onClose: () => void;
}) {
  const { user, logout } = useAuth();
  const [query, setQuery] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingValue, setEditingValue] = useState("");
  const [profileOpen, setProfileOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    function handleKey(e: globalThis.KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [isOpen, onClose]);

  function selectAndClose(sessionId: string) {
    onSelect(sessionId);
    onClose();
  }

  function newChatAndClose() {
    onNewChat();
    onClose();
  }

  function newProjectAndClose() {
    onNewProject();
    onClose();
  }

  function openSettingsAndClose() {
    setProfileOpen(false);
    onOpenSettings();
    onClose();
  }

  const filtered = useMemo(() => {
    if (!query.trim()) return projects;
    const q = query.toLowerCase();
    return projects.filter((p) => p.project_name.toLowerCase().includes(q));
  }, [projects, query]);

  function startEditing(sessionId: string, currentName: string) {
    setEditingId(sessionId);
    setEditingValue(currentName);
    requestAnimationFrame(() => inputRef.current?.select());
  }

  function commitEdit(sessionId: string, originalName: string) {
    const trimmed = editingValue.trim();
    setEditingId(null);
    if (trimmed && trimmed !== originalName) {
      onRename(sessionId, trimmed);
    }
  }

  function handleEditKeyDown(
    e: KeyboardEvent<HTMLInputElement>,
    sessionId: string,
    originalName: string,
  ) {
    if (e.key === "Enter") {
      e.preventDefault();
      commitEdit(sessionId, originalName);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setEditingId(null);
    }
  }

  const displayName = user?.name || "Your profile";

  return (
    <>
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-ink/30 md:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}
      <aside
        role="navigation"
        aria-label="Projects"
        className={`safe-top safe-bottom fixed inset-y-0 left-0 z-50 flex w-[85vw] max-w-80 -translate-x-full flex-col bg-surface shadow-lg transition-transform duration-200 ease-out md:static md:z-auto md:h-full md:w-72 md:max-w-none md:translate-x-0 md:border-r md:border-border md:shadow-none ${
          isOpen ? "translate-x-0" : ""
        }`}
      >
        <div className="border-b border-border p-4">
          <div className="flex items-center justify-between">
            <h1 className="font-display text-lg text-ink">Tarzyna</h1>
            <button
              onClick={onClose}
              aria-label="Close menu"
              className="rounded-md p-2 text-ink-faint hover:bg-paper hover:text-ink md:hidden"
            >
              <X size={18} />
            </button>
          </div>
          <button
            onClick={newChatAndClose}
            className="mt-3 flex w-full items-center justify-center gap-2 rounded-md bg-accent py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-strong"
          >
            <MessageSquarePlus size={15} />
            New chat
          </button>
          <button
            onClick={newProjectAndClose}
            className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-md border border-border-strong py-2 text-xs font-medium text-ink-muted transition-colors hover:border-accent hover:text-accent"
          >
            <Plus size={13} />
            New project (structured)
          </button>
          <button
            onClick={onToggleArchived}
            className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-md border border-border-strong py-2 text-xs font-medium text-ink-muted transition-colors hover:border-accent hover:text-accent"
          >
            <Archive size={13} />
            {showArchived ? "Hide archived" : "Show archived"}
          </button>
        </div>

        <div className="border-b border-border p-3">
          <div className="flex items-center gap-2 rounded-md border border-border-strong bg-paper px-2.5 py-2">
            <Search size={14} className="shrink-0 text-ink-faint" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search projects"
              aria-label="Search projects"
              className="w-full bg-transparent text-sm text-ink outline-none placeholder:text-ink-faint"
            />
          </div>
        </div>

        <nav className="min-h-0 flex-1 overflow-y-auto p-2">
          {filtered.length === 0 && (
            <p className="px-2 py-4 text-center text-sm text-ink-faint">
              {projects.length === 0 ? "No conversations yet." : "No matches."}
            </p>
          )}
          <ul className="space-y-0.5">
            {filtered.map((project) => {
              const isEditing = editingId === project.session_id;
              const isActive = project.session_id === activeSessionId;
              return (
                <li key={project.session_id} className="group relative">
                  {isEditing ? (
                    <input
                      ref={inputRef}
                      autoFocus
                      value={editingValue}
                      onChange={(e) => setEditingValue(e.target.value)}
                      onKeyDown={(e) =>
                        handleEditKeyDown(
                          e,
                          project.session_id,
                          project.project_name,
                        )
                      }
                      onBlur={() =>
                        commitEdit(project.session_id, project.project_name)
                      }
                      className="w-full rounded-md border border-accent bg-surface px-3 py-2 text-sm text-ink outline-none"
                    />
                  ) : (
                    <button
                      onClick={() => selectAndClose(project.session_id)}
                      className={`w-full rounded-md px-3 py-2.5 text-left text-sm transition-colors ${
                        isActive
                          ? "bg-accent-soft text-accent-strong"
                          : "text-ink hover:bg-paper"
                      }`}
                    >
                      <span className="flex min-w-0 items-center gap-2 pr-16">
                        <span className="min-w-0 truncate font-medium">
                          {project.project_name}
                        </span>
                        {project.is_archived && (
                          <span
                            className="shrink-0 rounded-full border border-border-strong bg-paper px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-ink-muted"
                            title="This project is archived"
                          >
                            Archived
                          </span>
                        )}
                      </span>
                      {!project.is_casual && (
                        <span className="block truncate pr-16 text-xs text-ink-faint">
                          {project.module} ·{" "}
                          {project.current_phase.replace(/_/g, " ")}
                        </span>
                      )}
                    </button>
                  )}
                  {!isEditing && (
                    <div className="absolute right-1 top-1 flex gap-0.5 opacity-100 md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          startEditing(project.session_id, project.project_name);
                        }}
                        aria-label={`Rename ${project.project_name}`}
                        className="rounded-md p-2 text-ink-faint hover:bg-surface hover:text-ink"
                      >
                        <Pencil size={13} />
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onArchive(project.session_id);
                        }}
                        aria-label={`Archive ${project.project_name}`}
                        className="rounded-md p-2 text-ink-faint hover:bg-surface hover:text-ink"
                      >
                        <Archive size={13} />
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onDelete(project.session_id);
                        }}
                        aria-label={`Delete ${project.project_name}`}
                        className="rounded-md p-2 text-ink-faint hover:bg-surface hover:text-danger"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="relative border-t border-border p-3">
          {profileOpen && (
            <div className="absolute bottom-full left-3 right-3 mb-2 overflow-hidden rounded-md border border-border bg-surface shadow-lg">
              <div className="flex items-center gap-2 p-3">
                <Avatar
                  profilePictureUrl={user?.profile_picture_url}
                  name={user?.name}
                  size="md"
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-ink">
                    {displayName}
                  </p>
                  {user?.email && (
                    <p className="truncate text-xs text-ink-muted">
                      {user.email}
                    </p>
                  )}
                </div>
              </div>
              <button
                type="button"
                onClick={openSettingsAndClose}
                className="flex w-full items-center gap-2 border-t border-border px-3 py-2 text-left text-xs text-ink-muted hover:bg-paper hover:text-ink"
              >
                <SettingsIcon size={14} />
                Settings
              </button>
              <button
                type="button"
                onClick={logout}
                className="flex w-full items-center gap-2 border-t border-border px-3 py-2 text-left text-xs text-ink-muted hover:bg-paper hover:text-danger"
              >
                <LogOut size={14} />
                Log out
              </button>
            </div>
          )}
          <button
            onClick={() => setProfileOpen((open) => !open)}
            aria-label="Profile menu"
            aria-expanded={profileOpen}
            className="flex w-full items-center justify-between gap-2 rounded-md p-2 text-left hover:bg-paper"
          >
            <span className="flex min-w-0 items-center gap-2">
              <Avatar
                profilePictureUrl={user?.profile_picture_url}
                name={user?.name}
                size="sm"
              />
              <span className="truncate text-xs text-ink-muted">
                {displayName}
              </span>
            </span>
            <ChevronDown
              size={15}
              className={`shrink-0 text-ink-faint transition-transform ${
                profileOpen ? "rotate-180" : ""
              }`}
            />
          </button>
        </div>
      </aside>
    </>
  );
}