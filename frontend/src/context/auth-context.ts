import { createContext } from "react";
import type { User } from "../types";

export interface AuthContextValue {
  user: User | null;
  loading: boolean;
  verifyOtp: (pendingAuthRef: string, code: string) => Promise<void>;
  updateAccountSettings: (name: string) => Promise<void>;
  uploadProfilePicture: (file: File) => Promise<void>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>;
  deleteAccount: () => Promise<void>;
  logout: () => Promise<void>;
  logoutAll: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);