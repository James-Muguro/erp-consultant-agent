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
  onAuthExpired,
  setToken,
} from "../api/client";
import { AuthContext } from "./auth-context";
import type { SignupPayload, User } from "../types";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  // Initial loading is derived from the presence of a token: no token
  // means there is nothing to resolve, so the initial render is not a
  // loading render. This avoids a synchronous setLoading in the
  // bootstrap effect (flagged by react/set-state-in-effect).
  const [loading, setLoading] = useState(() => getToken() !== null);

  // The API client fires this whenever a protected request returns 401.
  useEffect(() => {
    return onAuthExpired(() => {
      setUser(null);
    });
  }, []);

  // Bootstrap: if a token is present, resolve the current user. The
  // cancellation flag protects against the StrictMode double-invoke in
  // development and against unmount-during-fetch.
  useEffect(() => {
    if (!getToken()) {
      return;
    }
    let cancelled = false;

    api
      .me()
      .then((u) => {
        if (!cancelled) setUser(u);
      })
      .catch((err: unknown) => {
        // Only a genuine auth failure clears the token. A transient
        // network error must NOT log the user out of a project they
        // may have been working on for weeks. `ApiError.kind` is the
        // discriminator.
        if (cancelled) return;
        if (err instanceof ApiError && err.kind === "auth") {
          clearToken();
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const { access_token, expires_in_minutes } = await api.login(email, password);
    setToken(access_token, expires_in_minutes);
    try {
      const me = await api.me();
      setUser(me);
    } catch (err) {
      clearToken();
      throw err;
    }
  }, []);

  const signup = useCallback(async (payload: SignupPayload) => {
    const { access_token, expires_in_minutes } = await api.signup(payload);
    setToken(access_token, expires_in_minutes);
    try {
      const me = await api.me();
      setUser(me);
    } catch (err) {
      clearToken();
      throw err;
    }
  }, []);

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

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        login,
        signup,
        updateAccountSettings,
        uploadProfilePicture,
        changePassword,
        deleteAccount,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}