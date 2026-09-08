import { useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Archive, ChevronDown, LogOut, MessageSquarePlus, Pencil, Plus, Search, Trash2 } from "lucide-react";
import type { ProjectSummary } from "../types";
import { useAuth } from "../context/AuthContext";

export function Sidebar({
  projects,
  activeSessionId,
  onSelect,
  onNewChat,
  onNewProject,
  onRename,
  onArchive,
  onDelete,
  showArchived,
  onToggleArchived,
}: {
  projects: ProjectSummary[];
  activeSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onNewChat: () => void;
  onNewProject: () => void;
  onRename: (sessionId: string, newName: string) => void;
  onArchive: (sessionId: string) => void;
  onDelete: (sessionId: string) => void;
  showArchived: boolean;
  onToggleArchived: () => void;
}) {
  const { user, logout, updateAccountSettings, changePassword, deleteAccount } = useAuth();
  const [query, setQuery] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingValue, setEditingValue] = useState("");
  const [profileOpen, setProfileOpen] = useState(false);
  const [editingProfile, setEditingProfile] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [profileName, setProfileName] = useState(user?.name ?? "");
  const [profilePictureUrl, setProfilePictureUrl] = useState(user?.profile_picture_url ?? "");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [profileError, setProfileError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const filtered = useMemo(() => {
    if (!query.trim()) return projects;
    const q = query.toLowerCase();
    return projects.filter((p) => p.project_name.toLowerCase().includes(q));
  }, [projects, query]);

  function startEditing(sessionId: string, currentName: string) {
    setEditingId(sessionId);
    setEditingValue(currentName);
    // Focus happens after the input mounts - autoFocus on the input
    // itself covers this, but requestAnimationFrame ensures the text is
    // also selected for a fast overwrite.
    requestAnimationFrame(() => inputRef.current?.select());
  }

  function commitEdit(sessionId: string, originalName: string) {
    const trimmed = editingValue.trim();
    setEditingId(null);
    if (trimmed && trimmed !== originalName) {
      onRename(sessionId, trimmed);
    }
  }

  function handleEditKeyDown(e: KeyboardEvent<HTMLInputElement>, sessionId: string, originalName: string) {
    if (e.key === "Enter") {
      e.preventDefault();
      commitEdit(sessionId, originalName);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setEditingId(null);
    }
  }

  const displayName = user?.name || "Your profile";
  const initials = (user?.name || "??")
    .trim()
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  async function saveProfile() {
    setProfileError(null);
    try {
      await updateAccountSettings(profileName, profilePictureUrl);
      setEditingProfile(false);
    } catch (error) {
      setProfileError(error instanceof Error ? error.message : "Could not update profile.");
    }
  }

  async function savePassword() {
    setProfileError(null);
    try {
      await changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
    } catch (error) {
      setProfileError(error instanceof Error ? error.message : "Could not change password.");
    }
  }

  async function removeAccount() {
    if (!window.confirm("Delete your account and all of its chats? This cannot be undone.")) return;
    try {
      await deleteAccount();
    } catch (error) {
      setProfileError(error instanceof Error ? error.message : "Could not delete account.");
    }
  }

  return (
    <aside className="flex max-h-[45vh] w-full shrink-0 flex-col border-b border-border bg-surface md:h-full md:max-h-none md:w-72 md:border-b-0 md:border-r">
      <div className="border-b border-border p-4">
        <h1 className="font-display text-lg text-ink">ERP Consultant AI</h1>
        <button
          onClick={onNewChat}
          className="mt-3 flex w-full items-center justify-center gap-2 rounded-md bg-accent py-2 text-sm font-medium text-white transition-colors hover:bg-accent-strong"
        >
          <MessageSquarePlus size={15} />
          New chat
        </button>
        <button
          onClick={onNewProject}
          className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-md border border-border py-1.5 text-xs font-medium text-ink-muted transition-colors hover:border-accent hover:text-accent"
        >
          <Plus size={13} />
          New project (structured)
        </button>
        <button
          onClick={onToggleArchived}
          className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-md border border-border py-1.5 text-xs font-medium text-ink-muted transition-colors hover:border-accent hover:text-accent"
        >
          <Archive size={13} />
          {showArchived ? "Hide archived" : "Show archived"}
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

      <nav className="min-h-0 flex-1 overflow-y-auto p-2">
        {filtered.length === 0 && (
          <p className="px-2 py-4 text-center text-sm text-ink-faint">
            {projects.length === 0 ? "No conversations yet." : "No matches."}
          </p>
        )}
        <ul className="space-y-0.5">
          {filtered.map((project) => {
            const isEditing = editingId === project.session_id;
            return (
              <li key={project.session_id} className="group relative">
                {isEditing ? (
                  <input
                    ref={inputRef}
                    autoFocus
                    value={editingValue}
                    onChange={(e) => setEditingValue(e.target.value)}
                    onKeyDown={(e) => handleEditKeyDown(e, project.session_id, project.project_name)}
                    onBlur={() => commitEdit(project.session_id, project.project_name)}
                    className="w-full rounded-md border border-accent bg-surface px-3 py-2 text-sm text-ink outline-none"
                  />
                ) : (
                  <button
                    onClick={() => onSelect(project.session_id)}
                    className={`w-full rounded-md px-3 py-2 text-left text-sm transition-colors ${
                      project.session_id === activeSessionId
                        ? "bg-accent-soft text-accent-strong"
                        : "text-ink hover:bg-paper"
                    }`}
                  >
                    <span className="block truncate pr-12 font-medium">{project.project_name}</span>
                    {!project.is_casual && (
                      <span className="block truncate pr-12 text-xs text-ink-faint">
                        {project.module} · {project.current_phase.replace(/_/g, " ")}
                      </span>
                    )}
                  </button>
                )}
                {!isEditing && (
                  <div className="absolute right-1.5 top-1.5 hidden gap-1 group-hover:flex">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        startEditing(project.session_id, project.project_name);
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
                      className="rounded-sm p-1 text-ink-faint hover:bg-surface hover:text-ink"
                    >
                      <Archive size={13} />
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onDelete(project.session_id);
                      }}
                      title="Delete"
                      className="rounded-sm p-1 text-ink-faint hover:bg-surface hover:text-danger"
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
          <div className="absolute bottom-full left-3 right-3 mb-2 max-h-[70vh] overflow-y-auto rounded-md border border-border bg-surface p-3 shadow-lg">
            <div className="flex items-center gap-2">
              {user?.profile_picture_url ? (
                <img src={user.profile_picture_url} alt="" className="h-9 w-9 rounded-full object-cover" />
              ) : (
                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent-strong">
                  {initials}
                </span>
              )}
              <p className="truncate text-sm font-medium text-ink">{displayName}</p>
            </div>
            <dl className="mt-2 space-y-1 text-xs text-ink-muted">
              <div className="flex justify-between gap-3">
                <dt>Email</dt>
                <dd className="truncate">{user?.email}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt>Member since</dt>
                <dd>{user?.created_at ? new Date(user.created_at).toLocaleDateString() : "-"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt>ID</dt>
                <dd className="max-w-[9rem] truncate" title={user?.id}>{user?.id}</dd>
              </div>
            </dl>
            {profileError && <p className="mt-2 text-xs text-danger">{profileError}</p>}
            {!editingProfile && !settingsOpen && (
              <div className="mt-3 flex gap-2">
                <button
                  type="button"
                  onClick={() => setEditingProfile(true)}
                  className="flex-1 rounded-sm border border-border px-2 py-1.5 text-xs text-ink-muted hover:border-accent hover:text-accent"
                >
                  Edit profile
                </button>
                <button
                  type="button"
                  onClick={() => setSettingsOpen(true)}
                  className="flex-1 rounded-sm border border-border px-2 py-1.5 text-xs text-ink-muted hover:border-accent hover:text-accent"
                >
                  Account settings
                </button>
              </div>
            )}
            {editingProfile && (
              <div className="mt-3 space-y-2">
                <input
                  value={profileName}
                  onChange={(e) => setProfileName(e.target.value)}
                  placeholder="Name"
                  className="w-full rounded-sm border border-border bg-paper px-2 py-1.5 text-xs text-ink outline-none focus:border-accent"
                />
                <input
                  value={profilePictureUrl}
                  onChange={(e) => setProfilePictureUrl(e.target.value)}
                  placeholder="Profile picture URL"
                  className="w-full rounded-sm border border-border bg-paper px-2 py-1.5 text-xs text-ink outline-none focus:border-accent"
                />
                <div className="flex gap-2">
                  <button type="button" onClick={saveProfile} className="flex-1 rounded-sm bg-accent px-2 py-1.5 text-xs text-white hover:bg-accent-strong">Save</button>
                  <button type="button" onClick={() => setEditingProfile(false)} className="flex-1 rounded-sm border border-border px-2 py-1.5 text-xs text-ink-muted">Cancel</button>
                </div>
              </div>
            )}
            {settingsOpen && (
              <div className="mt-3 space-y-2">
                <p className="text-xs font-medium text-ink">Account settings</p>
                <input
                  type="password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  placeholder="Current password"
                  className="w-full rounded-sm border border-border bg-paper px-2 py-1.5 text-xs text-ink outline-none focus:border-accent"
                />
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="New password"
                  className="w-full rounded-sm border border-border bg-paper px-2 py-1.5 text-xs text-ink outline-none focus:border-accent"
                />
                <button type="button" onClick={savePassword} className="w-full rounded-sm border border-border px-2 py-1.5 text-xs text-ink-muted hover:border-accent hover:text-accent">Change password</button>
                <button type="button" onClick={removeAccount} className="w-full rounded-sm border border-danger px-2 py-1.5 text-xs text-danger hover:bg-danger-soft">Delete account</button>
                <button type="button" onClick={() => setSettingsOpen(false)} className="w-full px-2 py-1 text-xs text-ink-faint">Back</button>
              </div>
            )}
            <button
              onClick={logout}
              className="mt-3 flex w-full items-center gap-2 rounded-sm border border-border px-2 py-1.5 text-left text-xs text-ink-muted hover:border-danger hover:text-danger"
            >
              <LogOut size={14} />
              Log out
            </button>
          </div>
        )}
        <button
          onClick={() => setProfileOpen((open) => !open)}
          title="Profile"
          className="flex w-full items-center justify-between gap-2 rounded-md p-1 text-left hover:bg-paper"
        >
          <span className="flex min-w-0 items-center gap-2">
            {user?.profile_picture_url ? (
              <img src={user.profile_picture_url} alt="" className="h-7 w-7 shrink-0 rounded-full object-cover" />
            ) : (
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent-soft text-[10px] font-semibold text-accent-strong">{initials}</span>
            )}
            <span className="truncate text-xs text-ink-muted">{displayName}</span>
          </span>
          <ChevronDown size={15} className={`shrink-0 text-ink-faint transition-transform ${profileOpen ? "rotate-180" : ""}`} />
        </button>
      </div>
    </aside>
  );
}