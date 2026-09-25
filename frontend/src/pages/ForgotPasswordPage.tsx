import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";

// Identical regardless of whether the email exists — matches the
// backend's enumeration-resistant contract.
const GENERIC_REQUEST_MESSAGE =
  "If an account with that email exists, a password reset email has been sent.";

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!email.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.requestPasswordReset(email.trim());
      setSent(true);
    } catch (err) {
      // Only client-side validation errors (e.g. malformed email
      // rejected by the backend's schema) are surfaced specifically.
      // Every other outcome still shows the generic confirmation.
      if (err instanceof ApiError && err.status === 422) {
        setError(err.message);
      } else {
        setSent(true);
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="font-display text-3xl text-ink">Reset your password</h1>
        </div>

        <div className="rounded-md border border-border bg-surface p-6">
          {sent ? (
            <div className="space-y-4 text-center">
              <p className="text-sm text-ink-muted">{GENERIC_REQUEST_MESSAGE}</p>
              <p className="text-xs text-ink-faint">
                The link expires shortly. If you don't see it, check your spam
                folder.
              </p>
              <Link
                to="/login"
                className="inline-block text-sm text-accent-strong underline"
              >
                Back to sign in
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label htmlFor="reset-email" className="mb-1 block text-sm text-ink-muted">
                  Email
                </label>
                <input
                  id="reset-email"
                  type="email"
                  required
                  autoComplete="email"
                  autoFocus
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@company.com"
                  className="w-full rounded-md border border-border-strong bg-surface px-3 py-2.5 text-base text-ink outline-none focus:border-accent sm:text-sm"
                />
              </div>

              {error && (
                <p role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={submitting || !email.trim()}
                className="w-full rounded-md bg-accent py-2 text-sm font-medium text-white transition-colors hover:bg-accent-strong disabled:opacity-60"
              >
                {submitting ? "Sending…" : "Send reset link"}
              </button>

              <div className="text-center">
                <Link to="/login" className="text-xs text-ink-faint underline">
                  Back to sign in
                </Link>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}