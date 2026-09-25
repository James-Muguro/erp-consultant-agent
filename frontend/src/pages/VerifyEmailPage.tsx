import { useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";

type ViewState = "verifying" | "success" | "error";

/**
 * Consumes the email-verification token from the URL.
 *
 * The backend returns the same generic 400 whether the token is
 * invalid, expired, or already used, so a single "invalid" state is
 * shown for all three. A resend form is offered alongside because the
 * user may have lost the original email.
 *
 * The "token missing from URL" case is derived during render, not set
 * from inside an effect. Effects run after commit, and calling
 * setState synchronously inside one triggers a second render pass
 * with no benefit. The condition is fully determined by the URL, so
 * it belongs in the render path.
 */
export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token");

  // State holds only the async verification outcome. The "no token"
  // branch is derived below, not stored.
  const [verificationState, setVerificationState] =
    useState<ViewState>("verifying");
  const [verificationError, setVerificationError] = useState<string | null>(
    null,
  );

  const [resendEmail, setResendEmail] = useState("");
  const [resending, setResending] = useState(false);
  const [resendSent, setResendSent] = useState(false);

  useEffect(() => {
    // Nothing to verify. The render path derives the error view from
    // the missing token; the effect is a no-op in that case.
    if (!token) return;

    let cancelled = false;
    (async () => {
      try {
        await api.verifyEmail(token);
        if (!cancelled) setVerificationState("success");
      } catch (err) {
        if (cancelled) return;
        setVerificationState("error");
        setVerificationError(
          err instanceof ApiError
            ? err.message
            : "This link is invalid or has expired.",
        );
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [token]);

  // Derived view state. When the URL has no token, the error view is
  // the correct first-paint state and no effect is needed to reach it.
  const state: ViewState = token ? verificationState : "error";
  const error = token
    ? verificationError
    : "This link is invalid or has expired.";

  async function handleResend(e: FormEvent) {
    e.preventDefault();
    if (!resendEmail.trim() || resending) return;
    setResending(true);
    setResendSent(false);
    try {
      await api.resendVerification(resendEmail.trim());
      // Same response regardless of whether the account exists.
      setResendSent(true);
    } catch {
      setResendSent(true);
    } finally {
      setResending(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="font-display text-3xl text-ink">Tarzyna</h1>
        </div>

        <div className="rounded-md border border-border bg-surface p-6">
          {state === "verifying" && (
            <p className="text-sm text-ink-muted">Verifying your email…</p>
          )}

          {state === "success" && (
            <div className="space-y-4 text-center">
              <h2 className="font-display text-lg text-ink">Email verified</h2>
              <p className="text-sm text-ink-muted">
                Your email is confirmed. You can now sign in.
              </p>
              <Link
                to="/login"
                className="inline-block text-sm text-accent-strong underline"
              >
                Go to sign in
              </Link>
            </div>
          )}

          {state === "error" && (
            <div className="space-y-4">
              <h2 className="font-display text-lg text-ink">Link expired</h2>
              <p className="text-sm text-ink-muted">{error}</p>

              <div className="border-t border-border pt-4">
                <p className="mb-2 text-sm text-ink-muted">
                  Request a new verification email:
                </p>
                <form onSubmit={handleResend} className="space-y-3">
                  <input
                    type="email"
                    required
                    autoComplete="email"
                    value={resendEmail}
                    onChange={(e) => setResendEmail(e.target.value)}
                    placeholder="you@company.com"
                    className="w-full rounded-md border border-border-strong bg-surface px-3 py-2.5 text-base text-ink outline-none focus:border-accent sm:text-sm"
                  />
                  <button
                    type="submit"
                    disabled={resending || !resendEmail.trim()}
                    className="w-full rounded-md border border-border-strong py-2 text-sm text-ink-muted hover:border-accent hover:text-accent disabled:opacity-60"
                  >
                    {resending ? "Sending…" : "Resend verification email"}
                  </button>
                </form>
                {resendSent && (
                  <p className="mt-2 text-xs text-ink-muted" role="status">
                    If an account with that email exists and requires
                    verification, a verification email has been sent.
                  </p>
                )}
              </div>

              <div className="pt-2 text-center">
                <Link to="/login" className="text-xs text-ink-faint underline">
                  Back to sign in
                </Link>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}