import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "../api/client";
import { AuthProvider } from "./AuthProvider";
import { useAuth } from "./AuthContext";
import type { AuthUser } from "./types";

const user: AuthUser = {
  id: "user-1",
  email: "dev@example.test",
  username: "dev",
  display_name: "Developer",
};
const fetchMock = vi.fn<typeof fetch>();

function AuthProbe() {
  const auth = useAuth();
  return (
    <div>
      <p>Auth status: {auth.status}</p>
      <p>
        Auth operation: {auth.operation.status}
        {auth.operation.status === "error"
          ? ` ${auth.operation.action} ${auth.operation.error.code}`
          : ""}
      </p>
      {auth.status === "authenticated" ? <p>Signed in as {auth.user.username}</p> : null}
      {auth.status === "anonymous" || auth.status === "loading" ? (
        <button
          type="button"
          onClick={() =>
            void auth.login({ email: user.email, password: "test-password" }).catch(() => undefined)
          }
        >
          Sign in
        </button>
      ) : null}
      {auth.status === "anonymous" || auth.status === "loading" ? (
        <button
          type="button"
          onClick={() =>
            void auth
              .register({
                email: user.email,
                password: "test-password",
                username: user.username,
              })
              .catch(() => undefined)
          }
        >
          Register
        </button>
      ) : null}
      {auth.status === "authenticated" ? (
        <button type="button" onClick={() => void auth.logout().catch(() => undefined)}>
          Sign out
        </button>
      ) : null}
    </div>
  );
}

function renderAuthProvider() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>
    </QueryClientProvider>,
  );
  return { ...view, queryClient };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function jsonResponse(
  body: unknown,
  status: number,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

beforeEach(() => {
  apiClient.setCsrfToken(null);
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  apiClient.setCsrfToken(null);
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

describe("AuthProvider", () => {
  it("restores the current user and retains the session CSRF token only in memory", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(user, 200, { "X-CSRF-Token": "csrf-from-session" }),
    );
    renderAuthProvider();

    expect(await screen.findByText("Auth status: authenticated")).toBeInTheDocument();
    expect(screen.getByText("Signed in as dev")).toBeInTheDocument();
    expect(apiClient.hasCsrfToken).toBe(true);
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("keeps transient session failures in an error state rather than treating them as anonymous", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          error: { code: "service_unavailable", message: "Try again later." },
          request_id: "req-2",
        },
        503,
      ),
    );
    renderAuthProvider();

    expect(await screen.findByText("Auth status: error")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign in" })).not.toBeInTheDocument();
  });

  it("rejects a malformed current-user response instead of accepting an untyped session", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ id: "user-1", email: user.email }, 200, {
        "X-CSRF-Token": "csrf-from-session",
      }),
    );
    renderAuthProvider();

    expect(await screen.findByText("Auth status: error")).toBeInTheDocument();
  });

  it("transitions through login and logout while attaching and clearing CSRF", async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) {
        return jsonResponse(
          { error: { code: "unauthenticated", message: "Not signed in." }, request_id: "req-1" },
          401,
        );
      }
      if (url.endsWith("/api/v1/auth/login")) {
        return jsonResponse(user, 200, { "X-CSRF-Token": "csrf-after-login" });
      }
      if (url.endsWith("/api/v1/auth/logout")) {
        expect(new Headers(init?.headers).get("X-CSRF-Token")).toBe("csrf-after-login");
        return jsonResponse({ status: "ok" }, 200);
      }
      throw new Error(`Unexpected API request: ${url}`);
    });
    renderAuthProvider();

    expect(await screen.findByText("Auth status: anonymous")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Signed in as dev")).toBeInTheDocument();
    await waitFor(() => expect(apiClient.hasCsrfToken).toBe(true));

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(apiClient.hasCsrfToken).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it.each(["login", "register"] as const)(
    "keeps the authenticated user and new CSRF token when an old bootstrap returns 401 after %s",
    async (action) => {
      const pendingMe = deferred<Response>();
      fetchMock.mockImplementation((input) => {
        const url = String(input);
        if (url.endsWith("/api/v1/me")) return pendingMe.promise;
        if (url.endsWith(`/api/v1/auth/${action}`)) {
          return Promise.resolve(jsonResponse(user, 200, { "X-CSRF-Token": `csrf-${action}` }));
        }
        throw new Error(`Unexpected API request: ${url}`);
      });
      const { queryClient } = renderAuthProvider();
      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

      fireEvent.click(
        screen.getByRole("button", { name: action === "login" ? "Sign in" : "Register" }),
      );
      expect(await screen.findByText("Auth status: authenticated")).toBeInTheDocument();
      expect(apiClient.hasCsrfToken).toBe(true);

      await act(async () => {
        pendingMe.resolve(
          jsonResponse(
            { error: { code: "unauthenticated", message: "Not signed in." }, request_id: "old-me" },
            401,
          ),
        );
        await new Promise((resolve) => setTimeout(resolve, 0));
      });

      expect(screen.getByText("Auth status: authenticated")).toBeInTheDocument();
      expect(queryClient.getQueryData(["auth", "current-user"])).toEqual(user);
      expect(apiClient.hasCsrfToken).toBe(true);
      expect(queryClient.getMutationCache().getAll()).toHaveLength(0);
    },
  );

  it("ignores a late successful bootstrap response after login", async () => {
    const pendingMe = deferred<Response>();
    let logoutCsrfToken: string | null = null;
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) return pendingMe.promise;
      if (url.endsWith("/api/v1/auth/login")) {
        return Promise.resolve(jsonResponse(user, 200, { "X-CSRF-Token": "csrf-after-login" }));
      }
      if (url.endsWith("/api/v1/auth/logout")) {
        logoutCsrfToken = new Headers(init?.headers).get("X-CSRF-Token");
        return Promise.resolve(jsonResponse({ status: "ok" }, 200));
      }
      throw new Error(`Unexpected API request: ${url}`);
    });
    const { queryClient } = renderAuthProvider();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Auth status: authenticated")).toBeInTheDocument();

    await act(async () => {
      pendingMe.resolve(jsonResponse(user, 200, { "X-CSRF-Token": "csrf-from-stale-bootstrap" }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(screen.getByText("Auth status: authenticated")).toBeInTheDocument();
    expect(queryClient.getQueryData(["auth", "current-user"])).toEqual(user);
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(logoutCsrfToken).toBe("csrf-after-login"));
  });

  it("rejects a second authentication operation while the first is pending", async () => {
    const pendingLogin = deferred<Response>();
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) {
        return Promise.resolve(
          jsonResponse(
            { error: { code: "unauthenticated", message: "Not signed in." }, request_id: "req-1" },
            401,
          ),
        );
      }
      if (url.endsWith("/api/v1/auth/login")) return pendingLogin.promise;
      if (url.endsWith("/api/v1/auth/register")) {
        return Promise.resolve(jsonResponse(user, 200, { "X-CSRF-Token": "csrf-register" }));
      }
      throw new Error(`Unexpected API request: ${url}`);
    });
    renderAuthProvider();

    expect(await screen.findByText("Auth status: anonymous")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/auth/login"))).toBe(
        true,
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Register" }));

    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/auth/register"))).toBe(
      false,
    );
    await act(async () => {
      pendingLogin.resolve(jsonResponse(user, 200, { "X-CSRF-Token": "csrf-login" }));
    });
    expect(await screen.findByText("Auth status: authenticated")).toBeInTheDocument();
  });

  it("does not retain registration credentials in the TanStack mutation cache", async () => {
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) {
        return jsonResponse(
          { error: { code: "unauthenticated", message: "Not signed in." }, request_id: "req-1" },
          401,
        );
      }
      if (url.endsWith("/api/v1/auth/register")) {
        return jsonResponse(user, 200, { "X-CSRF-Token": "csrf-register" });
      }
      throw new Error(`Unexpected API request: ${url}`);
    });
    const { queryClient } = renderAuthProvider();

    expect(await screen.findByText("Auth status: anonymous")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Register" }));
    expect(await screen.findByText("Signed in as dev")).toBeInTheDocument();
    expect(queryClient.getMutationCache().getAll()).toHaveLength(0);
  });

  it("reconciles an ambiguous logout failure through /me", async () => {
    let meRequests = 0;
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) {
        meRequests += 1;
        return Promise.resolve(
          meRequests === 1
            ? jsonResponse(user, 200, { "X-CSRF-Token": "csrf-before-logout" })
            : jsonResponse(
                {
                  error: { code: "unauthenticated", message: "Not signed in." },
                  request_id: "req-2",
                },
                401,
              ),
        );
      }
      if (url.endsWith("/api/v1/auth/logout")) {
        return Promise.reject(new TypeError("connection lost"));
      }
      throw new Error(`Unexpected API request: ${url}`);
    });
    renderAuthProvider();

    expect(await screen.findByText("Signed in as dev")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    expect(await screen.findByText("Auth status: anonymous")).toBeInTheDocument();
    expect(screen.getByText("Auth operation: error logout network_error")).toBeInTheDocument();
    expect(apiClient.hasCsrfToken).toBe(false);
    expect(
      fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/auth/logout")),
    ).toHaveLength(1);
  });

  it("surfaces definite logout rejection and preserves the confirmed active session", async () => {
    let meRequests = 0;
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) {
        meRequests += 1;
        return Promise.resolve(
          jsonResponse(user, 200, {
            "X-CSRF-Token": meRequests === 1 ? "csrf-before-rejection" : "csrf-refreshed",
          }),
        );
      }
      if (url.endsWith("/api/v1/auth/logout")) {
        expect(new Headers(init?.headers).get("X-CSRF-Token")).toBe("csrf-before-rejection");
        return Promise.resolve(
          jsonResponse(
            { error: { code: "csrf_validation_failed", message: "CSRF validation failed." } },
            403,
          ),
        );
      }
      throw new Error(`Unexpected API request: ${url}`);
    });
    renderAuthProvider();

    expect(await screen.findByText("Signed in as dev")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    expect(
      await screen.findByText("Auth operation: error logout csrf_validation_failed"),
    ).toBeInTheDocument();
    expect(screen.getByText("Auth status: authenticated")).toBeInTheDocument();
    expect(apiClient.hasCsrfToken).toBe(true);
    expect(meRequests).toBe(2);
  });
});
