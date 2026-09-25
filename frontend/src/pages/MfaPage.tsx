import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/useAuth";
import { api, ApiError } from "../api/client";

// Fixed generic messages matching the backend. Showing an identical
// message regardless of whether the pending-auth reference is still
// valid preserves the enumeration-resistant contract.
const GENERIC_OTP_RESEND_MESSAGE =
  "If this sign-in is still pending, a new code has been sent.";
const GENERIC_EXPIRED_MESSAGE =
  "This sign-in attempt has expired. Please sign in again.";

/**
 * Second step of login: verify the email OTP.
 *
 * The pending-auth reference arrives via React Router navigation state,
 * not via localStorage or the AuthContext. A direct navigation to
 * /mfa (a page refresh after state has been dropped, or a bookmarked
 * URL) renders the "expired" state and offers a link back to /login.
 *
 * No code length is validated client-side — the backend schema
 * enforces the configured length and returns a specific validation
 * error if the input is the wrong shape. Duplicating the length here
 * would risk drift if the setting changes.
 */
export function MfaPage() {
  const { user, verifyOtp } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);

  const pendingAuthRef =
    (location.state as { pendingAuthRef?: string } | null)?.pendingAuthRef ??
    null;

  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resendMessage, setResendMessage] = useState<string | null>(null);
  const [resending, setResending] = useState(false);

  useEffect(() => {
    if (pendingAuthRef) inputRef.current?.focus();
  }, [pendingAuthRef]);

  if (user) return <Navigate to="/" replace />;

  if (!pendingAuthRef) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-paper px-4">
        <div className="w-full max-w-sm rounded-md border border-border bg-surface p-6 text-center">
          <h1 className="font-display text-lg text-ink">Sign-in expired</h1>
          <p className="mt-2 text-sm text-ink-muted">{GENERIC_EXPIRED_MESSAGE}</p>
          <Link
            to="/login"
            className="mt-4 inline-block text-sm text-accent-strong underline"
          >
            Back to sign in
          </Link>
        </div>
      </div>
    );
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!code.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await verifyOtp(pendingAuthRef!, code.trim());
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Something went wrong. Try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleResend() {
    if (resending) return;
    setResending(true);
    setResendMessage(null);
    try {
      await api.resendOtp(pendingAuthRef!);
      // Generic message shown regardless of whether the backend sent a
      // new code (it throttles per-user) or treated the ref as unknown.
      setResendMessage(GENERIC_OTP_RESEND_MESSAGE);
    } catch {
      // Network failure still produces the same user-visible state so
      // the response shape doesn't leak backend behavior.
      setResendMessage(GENERIC_OTP_RESEND_MESSAGE);
    } finally {
      setResending(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="font-display text-3xl text-ink">Enter your code</h1>
          <p className="mt-2 text-sm text-ink-muted">
            We sent a verification code to your email address. It expires
            shortly — enter it below to finish signing in.
          </p>
        </div>

        <div className="rounded-md border border-border bg-surface p-6">
          <form onSubmit={handleSubmit} aria-busy={submitting} className="space-y-4">
            <div>
              <label htmlFor="otp-code" className="mb-1 block text-sm text-ink-muted">
                Verification code
              </label>
              <input
                ref={inputRef}
                id="otp-code"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]*"
                required
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                className="w-full rounded-md border border-border-strong bg-surface px-3 py-2.5 text-center text-xl tracking-widest text-ink outline-none focus:border-accent sm:text-base"
                placeholder="······"
              />
            </div>

            {error && (
              <p role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={submitting || !code.trim()}
              className="w-full rounded-md bg-accent py-2 text-sm font-medium text-white transition-colors hover:bg-accent-strong disabled:opacity-60"
            >
              {submitting ? "Verifying…" : "Verify and sign in"}
            </button>
          </form>

          <div className="mt-4 border-t border-border pt-4 text-center">
            <button
              type="button"
              onClick={handleResend}
              disabled={resending}
              className="text-xs text-ink-muted underline hover:text-accent disabled:opacity-60"
            >
              {resending ? "Sending…" : "Resend code"}
            </button>
            {resendMessage && (
              <p className="mt-2 text-xs text-ink-muted" role="status">
                {resendMessage}
              </p>
            )}
          </div>

          <div className="mt-4 text-center">
            <Link to="/login" className="text-xs text-ink-faint underline">
              Cancel
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}