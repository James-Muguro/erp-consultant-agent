import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, clearToken, getToken, setToken } from "../api/client";
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

  useEffect(() => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    api
      .me()
      .then(setUser)
      .catch(() => clearToken())
      .finally(() => setLoading(false));
  }, []);

  async function login(email: string, password: string) {
    const { access_token } = await api.login(email, password);
    setToken(access_token);
    setUser(await api.me());
  }

  async function signup(email: string, password: string) {
    const { access_token } = await api.signup(email, password);
    setToken(access_token);
    setUser(await api.me());
  }

  async function updateAccountSettings(name: string) {
    setUser(await api.updateAccountSettings(name));
  }

  async function uploadProfilePicture(file: File) {
    setUser(await api.uploadProfilePicture(file));
  }

  async function changePassword(currentPassword: string, newPassword: string) {
    await api.changePassword(currentPassword, newPassword);
  }

  async function deleteAccount() {
    await api.deleteAccount();
    clearToken();
    setUser(null);
  }

  function logout() {
    clearToken();
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, signup, updateAccountSettings, uploadProfilePicture, changePassword, deleteAccount, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
