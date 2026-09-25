import {
  useCallback,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  ApiError,
  api,
  clearToken,
  getToken,
  isTokenExpired,
  onAuthExpired,
  setToken,
} from "../api/client";
import { AuthContext } from "./auth-context";
import type { User } from "../types";

/**
 * Authentication state and lifecycle.
 *
 * The provider owns exactly two pieces of state: the resolved `user`
 * and the `loading` flag. The access token lives in the client
 * module's storage (localStorage) and is not duplicated here; the
 * refresh token lives exclusively in the backend-issued HttpOnly
 * cookie and is never touched by JS.
 *
 * Two-step login: `initiateLogin` verifies the password and returns
 * an opaque pending-auth reference. That reference is NEVER placed
 * into this context — the login page passes it to the MFA route via
 * navigation state, and the MFA page hands it back to `verifyOtp`.
 * Between the two steps the user is not considered authenticated.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // The API client fires this whenever a protected request returns 401.
  // Transition to logged-out here, in one place.
  useEffect(() => {
    return onAuthExpired(() => {
      setUser(null);
    });
  }, []);

  // Bootstrap. Runs once on mount. Attempts to restore a session using
  // the existing access token if one exists and is not expired;
  // otherwise (or on 401) falls through to a refresh attempt, which
  // succeeds only if the browser has a valid refresh cookie.
  //
  // A network error during the token-valid path is deliberately NOT
  // treated as an auth failure — the user's token stays in storage and
  // the next attempt can succeed.
  useEffect(() => {
    let cancelled = false;

    async function restore() {
      const existing = getToken();
      if (existing && !isTokenExpired()) {
        try {
          const u = await api.me();
          if (cancelled) return;
          setUser(u);
          return;
        } catch (err) {
          if (cancelled) return;
          if (!(err instanceof ApiError && err.kind === "auth")) {
            // Network or server problem. Leave local state intact.
            return;
          }
          clearToken();
        }
      } else if (existing) {
        clearToken();
      }

      // Refresh path. Uses the HttpOnly cookie; if there is no valid
      // session, the backend returns 401/403 and we stay logged out.
      try {
        const tokens = await api.refresh();
        if (cancelled) return;
        setToken(tokens.access_token, tokens.expires_in_minutes);
        const u = await api.me();
        if (cancelled) return;
        setUser(u);
      } catch {
        if (cancelled) return;
        clearToken();
        setUser(null);
      }
    }

    restore().finally(() => {
      if (!cancelled) setLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, []);

  const verifyOtp = useCallback(
    async (pendingAuthRef: string, code: string) => {
      const tokens = await api.verifyOtp(pendingAuthRef, code);
      setToken(tokens.access_token, tokens.expires_in_minutes);
      try {
        const me = await api.me();
        setUser(me);
      } catch (err) {
        clearToken();
        throw err;
      }
    },
    [],
  );

  const updateAccountSettings = useCallback(async (name: string) => {
    setUser(await api.updateAccountSettings(name));
  }, []);

  const uploadProfilePicture = useCallback(async (file: File) => {
    setUser(await api.uploadProfilePicture(file));
  }, []);

  const changePassword = useCallback(
    async (currentPassword: string, newPassword: string) => {
      await api.changePassword(currentPassword, newPassword);
    },
    [],
  );

  const deleteAccount = useCallback(async () => {
    await api.deleteAccount();
    clearToken();
    setUser(null);
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // Logout is best-effort from the client's perspective. Even if
      // the request fails (network, missing CSRF), the local session
      // is cleared; the backend will clear or expire the refresh
      // cookie on its own schedule.
    }
    clearToken();
    setUser(null);
  }, []);

  const logoutAll = useCallback(async () => {
    try {
      await api.logoutAll();
    } catch {
      // Same rationale as logout.
    }
    clearToken();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        verifyOtp,
        updateAccountSettings,
        uploadProfilePicture,
        changePassword,
        deleteAccount,
        logout,
        logoutAll,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}