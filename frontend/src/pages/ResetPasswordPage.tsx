import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";

const MIN_PASSWORD_LENGTH = 12;

/**
 * Completes a password reset using the token from the URL.
 *
 * The backend returns the same generic 400 whether the token is
 * invalid, expired, or already used. The success path immediately
 * navigates the user to /login because all refresh sessions were
 * revoked server-side and a fresh sign-in is required.
 */
export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token");

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD_LENGTH;
  const mismatch = confirm.length > 0 && password !== confirm;
  const canSubmit =
    !!token && password.length >= MIN_PASSWORD_LENGTH && password === confirm;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!token || !canSubmit || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.completePasswordReset(token, password);
      navigate("/login", { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "This link is invalid or has expired.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="font-display text-3xl text-ink">Set a new password</h1>
        </div>

        <div className="rounded-md border border-border bg-surface p-6">
          {!token ? (
            <div className="space-y-4 text-center">
              <p className="text-sm text-ink-muted">
                This link is invalid or has expired.
              </p>
              <Link
                to="/forgot-password"
                className="inline-block text-sm text-accent-strong underline"
              >
                Request a new reset link
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label htmlFor="new-password" className="mb-1 block text-sm text-ink-muted">
                  New password
                </label>
                <input
                  id="new-password"
                  type="password"
                  required
                  minLength={MIN_PASSWORD_LENGTH}
                  maxLength={128}
                  autoComplete="new-password"
                  autoFocus
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={`At least ${MIN_PASSWORD_LENGTH} characters`}
                  className="w-full rounded-md border border-border-strong bg-surface px-3 py-2.5 text-base text-ink outline-none focus:border-accent sm:text-sm"
                />
                {tooShort && (
                  <p className="mt-1 text-xs text-danger">
                    Password must be at least {MIN_PASSWORD_LENGTH} characters.
                  </p>
                )}
              </div>

              <div>
                <label htmlFor="confirm-password" className="mb-1 block text-sm text-ink-muted">
                  Confirm new password
                </label>
                <input
                  id="confirm-password"
                  type="password"
                  required
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  className="w-full rounded-md border border-border-strong bg-surface px-3 py-2.5 text-base text-ink outline-none focus:border-accent sm:text-sm"
                />
                {mismatch && (
                  <p className="mt-1 text-xs text-danger">
                    Passwords do not match.
                  </p>
                )}
              </div>

              {error && (
                <p role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={submitting || !canSubmit}
                className="w-full rounded-md bg-accent py-2 text-sm font-medium text-white transition-colors hover:bg-accent-strong disabled:opacity-60"
              >
                {submitting ? "Updating…" : "Update password"}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}