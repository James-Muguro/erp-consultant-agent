import {
  createContext,
  useCallback,
  useContext,
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
import type { User } from "../types";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string) => Promise<void>;
  updateAccountSettings: (name: string) => Promise<void>;
  uploadProfilePicture: (file: File) => Promise<void>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>;
  deleteAccount: () => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // The API client fires this whenever a protected request returns 401.
  // We transition to the logged-out state here, in exactly one place,
  // instead of leaving a stale `user` object on screen while every
  // subsequent request silently fails.
  useEffect(() => {
    return onAuthExpired(() => {
      setUser(null);
    });
  }, []);

  // Bootstrap: if a token is present, resolve the current user. The
  // cancellation flag protects against the StrictMode double-invoke in
  // development and against unmount-during-fetch.
  useEffect(() => {
    let cancelled = false;

    if (!getToken()) {
      setLoading(false);
      return;
    }

    api
      .me()
      .then((u) => {
        if (!cancelled) setUser(u);
      })
      .catch((err: unknown) => {
        // Only a genuine auth failure clears the token. A transient
        // network error - hotel WiFi, proxy hiccup, backend restart -
        // must NOT log the user out of a project they may have been
        // working on for weeks. `ApiError.kind` is the discriminator.
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
      // Never leave a valid token paired with a null user - that state
      // renders the login page while a session actually exists, and
      // produces a confusing "signed in but not signed in" state after
      // a refresh.
      clearToken();
      throw err;
    }
  }, []);

  const signup = useCallback(async (email: string, password: string) => {
    const { access_token, expires_in_minutes } = await api.signup(email, password);
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

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}