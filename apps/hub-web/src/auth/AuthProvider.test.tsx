import {
  QueryClient,
  QueryClientProvider,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "../api/client";
import { getProtectedQueryIdentityGeneration } from "../app/protectedQueryCache";
import {
  personalRepositoryMutationClient,
  personalRepositoryMutationOptions,
  personalRepositoryQueryKeys,
} from "../repositories/queries";
import type { PersonalRepository } from "../api/repositories";
import { AuthProvider } from "./AuthProvider";
import { useAuth } from "./AuthContext";
import type { AuthUser } from "./types";

const user: AuthUser = {
  id: "user-1",
  email: "dev@example.test",
  username: "dev",
  display_name: "Developer",
};
const anotherUser: AuthUser = {
  id: "user-2",
  email: "another@example.test",
  username: "another",
  display_name: "Another Developer",
};
const cachedRepositoryList = { items: [], total: 0, limit: 50, offset: 0 };
const fetchMock = vi.fn<typeof fetch>();
const queryClients: QueryClient[] = [];

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

function renderAuthProvider(
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  }),
  showRepositoryMutationProbe = false,
  pendingProfileUpdate?: Promise<AuthUser>,
) {
  queryClients.push(queryClient);
  const view = render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <AuthProbe />
        {showRepositoryMutationProbe ? <RepositoryMutationProbe /> : null}
        {pendingProfileUpdate ? (
          <PendingProfileUpdateProbe pendingProfileUpdate={pendingProfileUpdate} />
        ) : null}
      </AuthProvider>
    </QueryClientProvider>,
  );
  return { ...view, queryClient };
}

function PendingProfileUpdateProbe({
  pendingProfileUpdate,
}: {
  pendingProfileUpdate: Promise<AuthUser>;
}) {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const [updated, setUpdated] = useState(false);

  if (auth.status !== "authenticated") return null;

  return (
    <>
      <button
        type="button"
        onClick={() => {
          const expectedUserId = auth.user.id;
          const identityGeneration = getProtectedQueryIdentityGeneration(
            queryClient,
            expectedUserId,
          );
          if (identityGeneration === null) return;
          void pendingProfileUpdate.then(async (updatedUser) => {
            await auth.updateUser(updatedUser, expectedUserId, identityGeneration);
            setUpdated(true);
          });
        }}
      >
        Apply pending profile update
      </button>
      <button type="button" onClick={() => void auth.retrySession()}>
        Refresh session
      </button>
      {updated ? <p>Profile update applied</p> : null}
    </>
  );
}

function RepositoryMutationProbe() {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const userId = auth.status === "authenticated" ? auth.user.id : "";
  const mutation = useMutation(
    personalRepositoryMutationOptions(queryClient, userId).create,
    personalRepositoryMutationClient(queryClient),
  );
  return (
    <div>
      {auth.status === "authenticated" ? (
        <>
          <button type="button" onClick={() => mutation.mutate({ name: "mutation-result" })}>
            Run repository mutation
          </button>
          <button type="button" onClick={() => void auth.retrySession()}>
            Refresh session
          </button>
        </>
      ) : null}
      <p>Repository mutation result: {mutation.data?.name ?? "none"}</p>
    </div>
  );
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
  for (const queryClient of queryClients.splice(0)) {
    personalRepositoryMutationClient(queryClient).clear();
    queryClient.clear();
  }
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
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const repositoryListKey = personalRepositoryQueryKeys.list(user.id);
    queryClient.setQueryData(repositoryListKey, cachedRepositoryList);
    renderAuthProvider(queryClient);

    expect(await screen.findByText("Auth status: anonymous")).toBeInTheDocument();
    expect(queryClient.getQueryData(repositoryListKey)).toBeUndefined();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Signed in as dev")).toBeInTheDocument();
    await waitFor(() => expect(apiClient.hasCsrfToken).toBe(true));

    queryClient.setQueryData(repositoryListKey, cachedRepositoryList);
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(apiClient.hasCsrfToken).toBe(false);
    expect(queryClient.getQueryData(repositoryListKey)).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("clears repository caches when session bootstrap resolves to another account", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(anotherUser, 200, { "X-CSRF-Token": "csrf-another-user" }),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const previousListKey = personalRepositoryQueryKeys.list(user.id);
    const nextListKey = personalRepositoryQueryKeys.list(anotherUser.id);
    queryClient.setQueryData(["auth", "current-user"], user);
    queryClient.setQueryData(previousListKey, cachedRepositoryList);
    queryClient.setQueryData(nextListKey, cachedRepositoryList);
    renderAuthProvider(queryClient);

    expect(await screen.findByText("Signed in as another")).toBeInTheDocument();
    expect(queryClient.getQueryData(previousListKey)).toBeUndefined();
    expect(queryClient.getQueryData(nextListKey)).toBeUndefined();
    expect(apiClient.hasCsrfToken).toBe(true);
  });

  it("ignores an old profile response after the authenticated identity changes", async () => {
    let meRequests = 0;
    const pendingProfileUpdate = deferred<AuthUser>();
    fetchMock.mockImplementation((input) => {
      if (String(input).endsWith("/api/v1/me")) {
        meRequests += 1;
        return Promise.resolve(
          jsonResponse(meRequests === 1 ? user : anotherUser, 200, {
            "X-CSRF-Token": `csrf-user-${meRequests}`,
          }),
        );
      }
      throw new Error(`Unexpected API request: ${String(input)}`);
    });
    const { queryClient } = renderAuthProvider(undefined, false, pendingProfileUpdate.promise);

    expect(await screen.findByText("Signed in as dev")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Apply pending profile update" }));
    fireEvent.click(screen.getByRole("button", { name: "Refresh session" }));
    expect(await screen.findByText("Signed in as another")).toBeInTheDocument();

    await act(async () => {
      pendingProfileUpdate.resolve({ ...user, display_name: "Stale profile response" });
    });
    expect(await screen.findByText("Profile update applied")).toBeInTheDocument();
    expect(screen.getByText("Signed in as another")).toBeInTheDocument();
    expect(queryClient.getQueryData(["auth", "current-user"])).toEqual(anotherUser);
  });

  it("ignores an old profile response after the same user starts a new session", async () => {
    const newSessionUser = { ...user, display_name: "Current session profile" };
    const pendingProfileUpdate = deferred<AuthUser>();
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) {
        return Promise.resolve(jsonResponse(user, 200, { "X-CSRF-Token": "csrf-from-session" }));
      }
      if (url.endsWith("/api/v1/auth/logout")) {
        return Promise.resolve(jsonResponse({ status: "ok" }, 200));
      }
      if (url.endsWith("/api/v1/auth/login")) {
        return Promise.resolve(
          jsonResponse(newSessionUser, 200, { "X-CSRF-Token": "csrf-new-session" }),
        );
      }
      throw new Error(`Unexpected API request: ${url}`);
    });
    const { queryClient } = renderAuthProvider(undefined, false, pendingProfileUpdate.promise);

    expect(await screen.findByText("Signed in as dev")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Apply pending profile update" }));
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByText("Auth status: anonymous")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Signed in as dev")).toBeInTheDocument();
    expect(queryClient.getQueryData(["auth", "current-user"])).toEqual(newSessionUser);

    await act(async () => {
      pendingProfileUpdate.resolve({ ...user, display_name: "Stale profile response" });
    });

    expect(await screen.findByText("Profile update applied")).toBeInTheDocument();
    expect(queryClient.getQueryData(["auth", "current-user"])).toEqual(newSessionUser);
  });

  it("applies a profile update when the initiating session remains current", async () => {
    const updatedUser = { ...user, display_name: "Updated Developer" };
    const pendingProfileUpdate = deferred<AuthUser>();
    fetchMock.mockImplementation((input) => {
      if (String(input).endsWith("/api/v1/me")) {
        return Promise.resolve(jsonResponse(user, 200, { "X-CSRF-Token": "csrf-session" }));
      }
      throw new Error(`Unexpected API request: ${String(input)}`);
    });
    const { queryClient } = renderAuthProvider(undefined, false, pendingProfileUpdate.promise);

    expect(await screen.findByText("Signed in as dev")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Apply pending profile update" }));

    await act(async () => {
      pendingProfileUpdate.resolve(updatedUser);
    });

    expect(await screen.findByText("Profile update applied")).toBeInTheDocument();
    expect(queryClient.getQueryData(["auth", "current-user"])).toEqual(updatedUser);
  });

  it("removes a settled repository mutation result when switching authenticated accounts", async () => {
    let meRequests = 0;
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) {
        meRequests += 1;
        return Promise.resolve(
          jsonResponse(meRequests === 1 ? user : anotherUser, 200, {
            "X-CSRF-Token": `csrf-user-${meRequests}`,
          }),
        );
      }
      if (url.endsWith("/api/v1/repositories") && init?.method === "POST") {
        const created: PersonalRepository = {
          id: "6f577861-febc-4c87-8949-e9201471141f",
          name: "mutation-result",
          description: null,
          visibility: "private",
          created_at: "2026-11-15T10:00:00Z",
          updated_at: "2026-11-15T10:00:00Z",
        };
        return Promise.resolve(jsonResponse(created, 201));
      }
      throw new Error(`Unexpected API request: ${url}`);
    });
    const { queryClient } = renderAuthProvider(undefined, true);

    expect(await screen.findByText("Signed in as dev")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run repository mutation" }));
    expect(
      await screen.findByText("Repository mutation result: mutation-result"),
    ).toBeInTheDocument();
    const repositoryMutationClient = personalRepositoryMutationClient(queryClient);
    expect(repositoryMutationClient.getMutationCache().getAll()).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Refresh session" }));
    expect(await screen.findByText("Signed in as another")).toBeInTheDocument();
    expect(screen.getByText("Repository mutation result: none")).toBeInTheDocument();
    expect(repositoryMutationClient.getMutationCache().getAll()).toHaveLength(0);
  });

  it("clears a settled repository mutation result on logout", async () => {
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) {
        return Promise.resolve(jsonResponse(user, 200, { "X-CSRF-Token": "csrf-user-1" }));
      }
      if (url.endsWith("/api/v1/repositories") && init?.method === "POST") {
        return Promise.resolve(
          jsonResponse(
            {
              id: "6f577861-febc-4c87-8949-e9201471141f",
              name: "mutation-result",
              description: null,
              visibility: "private",
              created_at: "2026-11-15T10:00:00Z",
              updated_at: "2026-11-15T10:00:00Z",
            } satisfies PersonalRepository,
            201,
          ),
        );
      }
      if (url.endsWith("/api/v1/auth/logout")) {
        return Promise.resolve(jsonResponse({ status: "ok" }, 200));
      }
      throw new Error(`Unexpected API request: ${url}`);
    });
    const { queryClient } = renderAuthProvider(undefined, true);

    expect(await screen.findByText("Signed in as dev")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run repository mutation" }));
    expect(
      await screen.findByText("Repository mutation result: mutation-result"),
    ).toBeInTheDocument();
    const repositoryMutationClient = personalRepositoryMutationClient(queryClient);
    expect(repositoryMutationClient.getMutationCache().getAll()).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    expect(await screen.findByText("Auth status: anonymous")).toBeInTheDocument();
    expect(screen.getByText("Repository mutation result: none")).toBeInTheDocument();
    expect(repositoryMutationClient.getMutationCache().getAll()).toHaveLength(0);
  });

  it("does not expose or invalidate a new user's cache when an old mutation settles after switching", async () => {
    let meRequests = 0;
    const pendingCreate = deferred<Response>();
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) {
        meRequests += 1;
        return Promise.resolve(
          jsonResponse(meRequests === 1 ? user : anotherUser, 200, {
            "X-CSRF-Token": `csrf-user-${meRequests}`,
          }),
        );
      }
      if (url.endsWith("/api/v1/repositories") && init?.method === "POST") {
        return pendingCreate.promise;
      }
      throw new Error(`Unexpected API request: ${url}`);
    });
    const { queryClient } = renderAuthProvider(undefined, true);

    expect(await screen.findByText("Signed in as dev")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run repository mutation" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) =>
            String(input).endsWith("/api/v1/repositories") && init?.method === "POST",
        ),
      ).toBe(true),
    );

    fireEvent.click(screen.getByRole("button", { name: "Refresh session" }));
    expect(await screen.findByText("Signed in as another")).toBeInTheDocument();
    expect(screen.getByText("Repository mutation result: none")).toBeInTheDocument();
    const nextUserListKey = personalRepositoryQueryKeys.list(anotherUser.id);
    queryClient.setQueryData(nextUserListKey, cachedRepositoryList);

    await act(async () => {
      pendingCreate.resolve(
        jsonResponse(
          {
            id: "6f577861-febc-4c87-8949-e9201471141f",
            name: "mutation-result",
            description: null,
            visibility: "private",
            created_at: "2026-11-15T10:00:00Z",
            updated_at: "2026-11-15T10:00:00Z",
          } satisfies PersonalRepository,
          201,
        ),
      );
    });

    expect(screen.getByText("Repository mutation result: none")).toBeInTheDocument();
    expect(queryClient.getQueryState(nextUserListKey)?.isInvalidated).toBe(false);
    expect(personalRepositoryMutationClient(queryClient).getMutationCache().getAll()).toHaveLength(
      0,
    );
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
    const { queryClient } = renderAuthProvider();

    expect(await screen.findByText("Signed in as dev")).toBeInTheDocument();
    const repositoryListKey = personalRepositoryQueryKeys.list(user.id);
    queryClient.setQueryData(repositoryListKey, cachedRepositoryList);
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    expect(await screen.findByText("Auth status: anonymous")).toBeInTheDocument();
    expect(screen.getByText("Auth operation: error logout network_error")).toBeInTheDocument();
    expect(apiClient.hasCsrfToken).toBe(false);
    expect(queryClient.getQueryData(repositoryListKey)).toBeUndefined();
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
