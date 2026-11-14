import { createContext, useContext } from "react";
import type { ApiError } from "../api/client";
import type { AuthUser, LoginCredentials, RegistrationDetails } from "./types";

export type AuthState =
  | { status: "loading"; user: null; error: null }
  | { status: "authenticated"; user: AuthUser; error: null }
  | { status: "anonymous"; user: null; error: null }
  | { status: "error"; user: null; error: ApiError };

export type AuthAction = "login" | "register" | "logout";

export type AuthOperationState =
  | { status: "idle" }
  | { status: "pending"; action: AuthAction }
  | { status: "error"; action: AuthAction; error: ApiError };

interface AuthActions {
  login: (credentials: LoginCredentials) => Promise<AuthUser>;
  register: (details: RegistrationDetails) => Promise<AuthUser>;
  logout: () => Promise<void>;
  retrySession: () => Promise<void>;
}

export type AuthContextValue = AuthState & AuthActions & { operation: AuthOperationState };

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider.");
  return context;
}
