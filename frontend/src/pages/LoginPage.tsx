import { useEffect, useRef, useState, type FormEvent } from "react";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../api/client";

export function LoginPage() {
  const { login, signup } = useAuth();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const emailRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    emailRef.current?.focus();
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await signup(email, password);
      }
    } catch (err) {
      if (err instanceof ApiError) {
        // ApiError.message is user-safe (Step 1 hardening). It carries the
        // backend's own wording for credentials failures ("Incorrect email
        // or password"), rate limits, and validation errors. `kind` and
        // `retryAfterSeconds` are available if we later want a distinct
        // presentation per failure category; for now the message is the
        // right thing to show.
        setError(err.message);
      } else {
        setError("Something went wrong. Try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="font-display text-3xl text-ink">Tarzyna</h1>
          <p className="mt-2 text-sm text-ink-muted">
            Next generation enterprise intelligence, assisting teams to design, develop, deploy, and master ERP solutions.
          </p>
        </div>

        <div className="rounded-md border border-border bg-surface p-6">
          <div className="mb-5 flex gap-1 rounded-md bg-paper p-1">
            <button
              type="button"
              onClick={() => setMode("login")}
              aria-pressed={mode === "login"}
              className={`flex-1 rounded-sm py-2 text-sm transition-colors ${
                mode === "login" ? "bg-surface font-medium text-ink shadow-sm" : "text-ink-muted"
              }`}
            >
              Log in
            </button>
            <button
              type="button"
              onClick={() => setMode("signup")}
              aria-pressed={mode === "signup"}
              className={`flex-1 rounded-sm py-2 text-sm transition-colors ${
                mode === "signup" ? "bg-surface font-medium text-ink shadow-sm" : "text-ink-muted"
              }`}
            >
              Sign up
            </button>
          </div>

          <form onSubmit={handleSubmit} aria-busy={submitting} className="space-y-4">
            <div>
              <label htmlFor="email" className="mb-1 block text-sm text-ink-muted">
                Email
              </label>
              <input
                ref={emailRef}
                id="email"
                type="email"
                required
                autoComplete="email"
                autoCapitalize="none"
                autoCorrect="off"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full rounded-md border border-border bg-surface px-3 py-2.5 text-base text-ink outline-none focus:border-accent sm:text-sm"
                placeholder="you@company.com"
              />
            </div>
            <div>
              <label htmlFor="password" className="mb-1 block text-sm text-ink-muted">
                Password
              </label>
              <input
                id="password"
                type="password"
                required
                minLength={8}
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-md border border-border bg-surface px-3 py-2.5 text-base text-ink outline-none focus:border-accent sm:text-sm"
                placeholder="At least 8 characters"
              />
            </div>

            {error && (
              <p role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded-md bg-accent py-2 text-sm font-medium text-white transition-colors hover:bg-accent-strong disabled:opacity-60"
            >
              {submitting ? "Please wait…" : mode === "login" ? "Log in" : "Create account"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}