import { useCallback, useMemo, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiClient } from "../api/client";
import {
  AuthContext,
  type AuthAction,
  type AuthContextValue,
  type AuthOperationState,
  type AuthState,
} from "./AuthContext";
import type { AuthStatusResponse, AuthUser, LoginCredentials, RegistrationDetails } from "./types";

const SESSION_QUERY_KEY = ["auth", "current-user"] as const;

function asApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  return new ApiError("Authentication could not be completed.", {
    status: null,
    code: "unexpected_error",
    requestId: null,
    cause: error,
  });
}

function requireUser(user: AuthUser | undefined): AuthUser {
  if (
    typeof user === "object" &&
    user !== null &&
    typeof user.id === "string" &&
    typeof user.email === "string" &&
    typeof user.username === "string" &&
    typeof user.display_name === "string"
  ) {
    return user;
  }
  throw new ApiError("The Hub API returned an empty authentication response.", {
    status: 200,
    code: "invalid_response",
    requestId: null,
  });
}

function requireCsrfToken(): void {
  if (apiClient.hasCsrfToken) return;
  throw new ApiError("The Hub API did not return a session CSRF token.", {
    status: 200,
    code: "missing_csrf_token",
    requestId: null,
  });
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const authOperationInProgress = useRef(false);
  const sessionRequestGeneration = useRef(0);
  const [operation, setOperation] = useState<AuthOperationState>({ status: "idle" });
  const sessionQuery = useQuery({
    queryKey: SESSION_QUERY_KEY,
    staleTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
    queryFn: async ({ signal }): Promise<AuthUser | null> => {
      if (authOperationInProgress.current) {
        return queryClient.getQueryData<AuthUser | null>(SESSION_QUERY_KEY) ?? null;
      }

      const requestGeneration = sessionRequestGeneration.current;
      try {
        signal.throwIfAborted();
        const user = requireUser(await apiClient.get<AuthUser>("/me", { signal }));
        signal.throwIfAborted();
        if (requestGeneration !== sessionRequestGeneration.current) {
          return queryClient.getQueryData<AuthUser | null>(SESSION_QUERY_KEY) ?? null;
        }
        requireCsrfToken();
        return user;
      } catch (error) {
        if (
          signal.aborted ||
          requestGeneration !== sessionRequestGeneration.current ||
          (error instanceof Error && error.name === "AbortError")
        ) {
          throw error;
        }
        const apiError = asApiError(error);
        if (apiError.status === 401) {
          apiClient.setCsrfToken(null);
          return null;
        }
        throw apiError;
      }
    },
  });

  const updateCurrentUser = useCallback(
    async (user: AuthUser) => {
      await queryClient.cancelQueries({ queryKey: SESSION_QUERY_KEY });
      queryClient.setQueryData(SESSION_QUERY_KEY, user);
    },
    [queryClient],
  );
  const runAuthOperation = useCallback(
    async <T,>(action: AuthAction, perform: () => Promise<T>): Promise<T> => {
      if (authOperationInProgress.current) {
        throw new ApiError("Another authentication operation is in progress.", {
          status: null,
          code: "auth_operation_in_progress",
          requestId: null,
        });
      }

      authOperationInProgress.current = true;
      sessionRequestGeneration.current += 1;
      setOperation({ status: "pending", action });
      let operationError: ApiError | null = null;
      try {
        await queryClient.cancelQueries({ queryKey: SESSION_QUERY_KEY });
        return await perform();
      } catch (error) {
        operationError = asApiError(error);
        setOperation({ status: "error", action, error: operationError });
        throw operationError;
      } finally {
        authOperationInProgress.current = false;
        if (operationError) {
          await queryClient.invalidateQueries({ queryKey: SESSION_QUERY_KEY });
        } else {
          setOperation({ status: "idle" });
        }
      }
    },
    [queryClient],
  );

  const login = useCallback(
    (credentials: LoginCredentials) =>
      runAuthOperation("login", async () => {
        const user = requireUser(
          await apiClient.post<AuthUser, LoginCredentials>("/auth/login", credentials),
        );
        requireCsrfToken();
        await updateCurrentUser(user);
        return user;
      }),
    [runAuthOperation, updateCurrentUser],
  );
  const register = useCallback(
    (details: RegistrationDetails) =>
      runAuthOperation("register", async () => {
        const user = requireUser(
          await apiClient.post<AuthUser, RegistrationDetails>("/auth/register", details),
        );
        requireCsrfToken();
        await updateCurrentUser(user);
        return user;
      }),
    [runAuthOperation, updateCurrentUser],
  );
  const logout = useCallback(
    () =>
      runAuthOperation("logout", async () => {
        const result = await apiClient.post<AuthStatusResponse>("/auth/logout");
        if (!result || result.status !== "ok") {
          throw new ApiError("The Hub API returned an invalid logout response.", {
            status: 200,
            code: "invalid_response",
            requestId: null,
          });
        }
        await queryClient.cancelQueries({ queryKey: SESSION_QUERY_KEY });
        apiClient.setCsrfToken(null);
        queryClient.setQueryData(SESSION_QUERY_KEY, null);
      }),
    [queryClient, runAuthOperation],
  );
  const refetchSession = sessionQuery.refetch;
  const retrySession = useCallback(async () => {
    await refetchSession();
  }, [refetchSession]);

  let state: AuthState;
  if (sessionQuery.isPending) {
    state = { status: "loading", user: null, error: null };
  } else if (sessionQuery.isError) {
    state = { status: "error", user: null, error: asApiError(sessionQuery.error) };
  } else if (sessionQuery.data) {
    state = { status: "authenticated", user: sessionQuery.data, error: null };
  } else {
    state = { status: "anonymous", user: null, error: null };
  }

  const value = useMemo<AuthContextValue>(
    () => ({ ...state, login, register, logout, retrySession, operation }),
    [state, login, register, logout, retrySession, operation],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
