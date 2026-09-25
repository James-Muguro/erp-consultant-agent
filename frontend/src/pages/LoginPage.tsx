import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { AccountType } from "../types";

const ACCOUNT_TYPE_OPTIONS: { value: AccountType; label: string; hint: string }[] = [
  {
    value: "erp_user",
    label: "ERP User",
    hint: "Use projects you're assigned to, with read access to relevant documents and training materials.",
  },
  {
    value: "functional_consultant",
    label: "Functional Consultant",
    hint: "Full consulting scope: requirements, process mapping, solution design, testing, and training.",
  },
  {
    value: "developer",
    label: "Developer",
    hint: "Solution design and implementation work, with read access to requirements.",
  },
  {
    value: "marketer",
    label: "Marketer",
    hint: "Case-study view, document generation, and content workflows.",
  },
  {
    value: "organization",
    label: "Organization",
    hint: "Create an organization workspace and become its owner.",
  },
];

// The same message the backend returns for signup. Displayed verbatim
// on the success screen so the response is genuinely identical whether
// the email was new or already registered.
const SIGNUP_SUCCESS_MESSAGE =
  "If this email address can be registered, a verification email has been sent. Please check your inbox to continue.";

export function LoginPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<"login" | "signup" | "signup-sent">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [accountType, setAccountType] = useState<AccountType>("functional_consultant");
  const [organizationName, setOrganizationName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const emailRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (mode !== "signup-sent") {
      emailRef.current?.focus();
    }
  }, [mode]);

  const selectedOption = ACCOUNT_TYPE_OPTIONS.find((o) => o.value === accountType)!;
  const isOrgSignup = mode === "signup" && accountType === "organization";

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (mode === "login") {
        const result = await api.initiateLogin(email, password);
        // Pass the pending-auth reference to the MFA step via
        // navigation state. It is NEVER stored in localStorage,
        // sessionStorage, or the AuthContext.
        navigate("/mfa", {
          state: { pendingAuthRef: result.pending_auth_ref },
        });
      } else if (mode === "signup") {
        await api.signup({
          email,
          password,
          account_type: accountType,
          organization_name: isOrgSignup ? organizationName.trim() : undefined,
        });
        setMode("signup-sent");
      }
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
          {mode === "signup-sent" ? (
            <div className="space-y-4">
              <h2 className="font-display text-lg text-ink">Check your email</h2>
              <p className="text-sm text-ink-muted">
                {SIGNUP_SUCCESS_MESSAGE}
              </p>
              <div className="flex flex-col gap-2 pt-2">
                <Link
                  to="/login"
                  onClick={() => setMode("login")}
                  className="text-center text-sm text-accent-strong underline"
                >
                  Back to sign in
                </Link>
                <Link
                  to="/verify-email"
                  className="text-center text-xs text-ink-muted underline"
                >
                  Didn't receive the email? Resend.
                </Link>
              </div>
            </div>
          ) : (
            <>
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
                {mode === "signup" && (
                  <div>
                    <label htmlFor="account_type" className="mb-1 block text-sm text-ink-muted">
                      Account type
                    </label>
                    <select
                      id="account_type"
                      value={accountType}
                      onChange={(e) => setAccountType(e.target.value as AccountType)}
                      className="w-full rounded-md border border-border-strong bg-surface px-3 py-2.5 text-base text-ink outline-none focus:border-accent sm:text-sm"
                    >
                      {ACCOUNT_TYPE_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                    <p className="mt-1 text-xs text-ink-faint">{selectedOption.hint}</p>
                  </div>
                )}

                {isOrgSignup && (
                  <div>
                    <label htmlFor="organization_name" className="mb-1 block text-sm text-ink-muted">
                      Organization name
                    </label>
                    <input
                      id="organization_name"
                      required
                      value={organizationName}
                      onChange={(e) => setOrganizationName(e.target.value)}
                      maxLength={200}
                      className="w-full rounded-md border border-border-strong bg-surface px-3 py-2.5 text-base text-ink outline-none focus:border-accent sm:text-sm"
                      placeholder="Your firm or company"
                    />
                    <p className="mt-1 text-xs text-ink-faint">
                      You will be the owner and can invite team members later.
                    </p>
                  </div>
                )}

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
                    className="w-full rounded-md border border-border-strong bg-surface px-3 py-2.5 text-base text-ink outline-none focus:border-accent sm:text-sm"
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
                    minLength={12}
                    maxLength={128}
                    autoComplete={mode === "login" ? "current-password" : "new-password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full rounded-md border border-border-strong bg-surface px-3 py-2.5 text-base text-ink outline-none focus:border-accent sm:text-sm"
                    placeholder="At least 12 characters"
                  />
                  {mode === "login" && (
                    <div className="mt-2 text-right">
                      <Link
                        to="/forgot-password"
                        className="text-xs text-ink-muted underline hover:text-accent"
                      >
                        Forgot password?
                      </Link>
                    </div>
                  )}
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
            </>
          )}
        </div>
      </div>
    </div>
  );
}