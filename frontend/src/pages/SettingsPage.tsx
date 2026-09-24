import { useRef, useState, type FormEvent } from "react";
import { Star, Trash2, Upload } from "lucide-react";
import { useAuth } from "../context/useAuth";
import { useConfirm } from "../context/useConfirm";
import { ApiError, api } from "../api/client";
import { Avatar } from "../components/Avatar";

export function SettingsPage() {
  const {
    user,
    updateAccountSettings,
    uploadProfilePicture,
    changePassword,
    deleteAccount,
  } = useAuth();

  if (!user) return null;

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-2xl px-4 py-8 sm:px-6 sm:py-12">
        <header className="mb-8">
          <h1 className="font-display text-2xl text-ink">Settings</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Manage your profile, security, and feedback.
          </p>
        </header>
        <div className="space-y-6">
          <ProfileSection
            initialName={user.name ?? ""}
            email={user.email}
            profilePictureUrl={user.profile_picture_url}
            onSaveName={updateAccountSettings}
            onUploadPicture={uploadProfilePicture}
          />
          <PasswordSection onChangePassword={changePassword} />
          <FeedbackSection />
          <DangerZoneSection onDeleteAccount={deleteAccount} />
        </div>
      </div>
    </div>
  );
}

function SettingsSection({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-md border border-border bg-surface">
      <div className="border-b border-border px-5 py-4">
        <h2 className="font-display text-base text-ink">{title}</h2>
        {description && (
          <p className="mt-1 text-xs text-ink-muted">{description}</p>
        )}
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

function ProfileSection({
  initialName,
  email,
  profilePictureUrl,
  onSaveName,
  onUploadPicture,
}: {
  initialName: string;
  email: string;
  profilePictureUrl: string | null;
  onSaveName: (name: string) => Promise<void>;
  onUploadPicture: (file: File) => Promise<void>;
}) {
  const [name, setName] = useState(initialName);
  const [pictureFile, setPictureFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const nameChanged = name.trim() !== initialName;
  const hasNewPicture = pictureFile !== null;
  const canSave = (nameChanged && name.trim().length > 0) || hasNewPicture;

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    if (!canSave) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      if (nameChanged && name.trim().length > 0) {
        await onSaveName(name.trim());
      }
      if (hasNewPicture && pictureFile) {
        await onUploadPicture(pictureFile);
      }
      setPictureFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setSaved(true);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not save your profile.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <SettingsSection title="Profile">
      <form onSubmit={handleSave} className="space-y-5">
        <div className="flex items-center gap-4">
          <Avatar
            profilePictureUrl={profilePictureUrl}
            name={name}
            size="lg"
            bordered
          />
          <div className="min-w-0">
            <label
              htmlFor="settings-picture"
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-border-strong px-3 py-1.5 text-xs font-medium text-ink-muted hover:border-accent hover:text-accent"
            >
              <Upload size={12} />
              {hasNewPicture ? "Change selection" : "Change picture"}
            </label>
            <input
              ref={fileInputRef}
              id="settings-picture"
              type="file"
              accept="image/jpeg,image/png,image/gif,image/webp"
              className="hidden"
              onChange={(e) => {
                setPictureFile(e.target.files?.[0] ?? null);
                setSaved(false);
              }}
            />
            {hasNewPicture && (
              <p className="mt-1 truncate text-xs text-ink-faint">
                {pictureFile?.name}
              </p>
            )}
            <p className="mt-1 text-xs text-ink-faint">
              JPEG, PNG, GIF, or WebP. Max 5MB.
            </p>
          </div>
        </div>

        <div>
          <label
            htmlFor="settings-name"
            className="mb-1 block text-sm text-ink-muted"
          >
            Name
          </label>
          <input
            id="settings-name"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setSaved(false);
            }}
            placeholder="Your name"
            className="w-full rounded-md border border-border-strong bg-paper px-3 py-2.5 text-base text-ink outline-none focus:border-accent sm:text-sm"
          />
        </div>

        <div>
          <label className="mb-1 block text-sm text-ink-muted">Email</label>
          <p className="truncate text-sm text-ink">{email}</p>
          <p className="mt-1 text-xs text-ink-faint">
            Email cannot be changed.
          </p>
        </div>

        {error && (
          <p
            role="alert"
            className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger"
          >
            {error}
          </p>
        )}
        {saved && (
          <p
            role="status"
            className="rounded-md bg-accent-soft px-3 py-2 text-sm text-accent-strong"
          >
            Profile saved.
          </p>
        )}

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={saving || !canSave}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-strong disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save changes"}
          </button>
        </div>
      </form>
    </SettingsSection>
  );
}

function PasswordSection({
  onChangePassword,
}: {
  onChangePassword: (
    currentPassword: string,
    newPassword: string,
  ) => Promise<void>;
}) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const canSubmit =
    current.length > 0 && next.length >= 12 && current !== next;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    setSaved(false);
    try {
      await onChangePassword(current, next);
      setCurrent("");
      setNext("");
      setSaved(true);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not change password.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <SettingsSection
      title="Password"
      description="Use at least 12 characters."
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label
            htmlFor="settings-current-password"
            className="mb-1 block text-sm text-ink-muted"
          >
            Current password
          </label>
          <input
            id="settings-current-password"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => {
              setCurrent(e.target.value);
              setSaved(false);
            }}
            className="w-full rounded-md border border-border-strong bg-paper px-3 py-2.5 text-base text-ink outline-none focus:border-accent sm:text-sm"
          />
        </div>
        <div>
          <label
            htmlFor="settings-new-password"
            className="mb-1 block text-sm text-ink-muted"
          >
            New password
          </label>
          <input
            id="settings-new-password"
            type="password"
            autoComplete="new-password"
            minLength={12}
            value={next}
            onChange={(e) => {
              setNext(e.target.value);
              setSaved(false);
            }}
            className="w-full rounded-md border border-border-strong bg-paper px-3 py-2.5 text-base text-ink outline-none focus:border-accent sm:text-sm"
          />
        </div>

        {error && (
          <p
            role="alert"
            className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger"
          >
            {error}
          </p>
        )}
        {saved && (
          <p
            role="status"
            className="rounded-md bg-accent-soft px-3 py-2 text-sm text-accent-strong"
          >
            Password changed.
          </p>
        )}

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={submitting || !canSubmit}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-strong disabled:opacity-50"
          >
            {submitting ? "Changing…" : "Change password"}
          </button>
        </div>
      </form>
    </SettingsSection>
  );
}

function FeedbackSection() {
  const [rating, setRating] = useState<number>(0);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  const canSubmit = rating > 0 || comment.trim().length > 0;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.submitFeedback(
        null,
        rating > 0 ? rating : null,
        comment.trim(),
      );
      setRating(0);
      setComment("");
      setSubmitted(true);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not submit feedback.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <SettingsSection
      title="Feedback"
      description="Tell us how the product is working for you. Feedback is not tied to a specific project."
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <span className="mb-1 block text-sm text-ink-muted">
            How would you rate your experience?
          </span>
          <div
            role="radiogroup"
            aria-label="Rating"
            className="flex items-center gap-1"
          >
            {[1, 2, 3, 4, 5].map((n) => {
              const selected = n <= rating;
              return (
                <button
                  key={n}
                  type="button"
                  role="radio"
                  aria-checked={rating === n}
                  aria-label={`${n} out of 5`}
                  onClick={() => {
                    setRating(n);
                    setSubmitted(false);
                  }}
                  className={`rounded-md p-1.5 transition-colors ${
                    selected
                      ? "text-accent"
                      : "text-ink-faint hover:text-ink-muted"
                  }`}
                >
                  <Star
                    size={22}
                    fill={selected ? "currentColor" : "none"}
                    aria-hidden="true"
                  />
                </button>
              );
            })}
          </div>
        </div>

        <div>
          <label
            htmlFor="settings-feedback"
            className="mb-1 block text-sm text-ink-muted"
          >
            Comments
          </label>
          <textarea
            id="settings-feedback"
            value={comment}
            onChange={(e) => {
              setComment(e.target.value);
              setSubmitted(false);
            }}
            maxLength={5000}
            rows={4}
            placeholder="What's working well? What could be better?"
            className="w-full resize-y rounded-md border border-border-strong bg-paper px-3 py-2.5 text-sm text-ink outline-none focus:border-accent"
          />
          <p className="mt-1 text-right text-xs text-ink-faint">
            {comment.length} / 5000
          </p>
        </div>

        {error && (
          <p
            role="alert"
            className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger"
          >
            {error}
          </p>
        )}
        {submitted && (
          <p
            role="status"
            className="rounded-md bg-accent-soft px-3 py-2 text-sm text-accent-strong"
          >
            Thanks - your feedback has been submitted.
          </p>
        )}

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={submitting || !canSubmit}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-strong disabled:opacity-50"
          >
            {submitting ? "Submitting…" : "Submit feedback"}
          </button>
        </div>
      </form>
    </SettingsSection>
  );
}

function DangerZoneSection({
  onDeleteAccount,
}: {
  onDeleteAccount: () => Promise<void>;
}) {
  const confirm = useConfirm();

  async function handleDelete() {
    const confirmed = await confirm({
      title: "Delete your account?",
      description:
        "This permanently removes your account, every project you own, and every uploaded document. This cannot be undone.",
      confirmLabel: "Delete account",
      variant: "danger",
      onConfirm: async () => {
        // On success AuthContext clears the token and user, so
        // RequireAuth redirects to /login. No navigate() call here.
        await onDeleteAccount();
      },
    });
    // Nothing to do on failure here - the dialog itself surfaces the
    // error and stays open so the user can retry or cancel.
    void confirmed;
  }

  return (
    <section className="rounded-md border border-danger/40 bg-surface">
      <div className="border-b border-danger/40 px-5 py-4">
        <h2 className="font-display text-base text-danger">Delete account</h2>
        <p className="mt-1 text-xs text-ink-muted">
          Permanently removes your account, every project you own, and all
          uploaded documents. This cannot be undone.
        </p>
      </div>
      <div className="p-5">
        <button
          type="button"
          onClick={handleDelete}
          className="inline-flex items-center gap-2 rounded-md border border-danger px-4 py-2 text-sm font-medium text-danger transition-colors hover:bg-danger hover:text-white"
        >
          <Trash2 size={14} aria-hidden="true" />
          Delete account
        </button>
      </div>
    </section>
  );
}