import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { apiClient } from "../api/client";
import { protectedQueryKey, transitionProtectedQueryIdentity } from "../app/protectedQueryCache";
import { RepositoryBrowsePanel } from "../components/RepositoryBrowsePanel";
import { clearPersonalRepositoryMutationState } from "../repositories/queries";
import { AuthProvider } from "./AuthProvider";
import { useAuth } from "./AuthContext";

const userA = {
  id: "user-a",
  email: "a@example.test",
  username: "user-a",
  display_name: "User A",
};
const userB = {
  id: "user-b",
  email: "b@example.test",
  username: "user-b",
  display_name: "User B",
};
const fetchMock = vi.fn<typeof fetch>();
const queryClients: QueryClient[] = [];

function AuthenticatedBrowseProbe() {
  const auth = useAuth();

  if (auth.status === "loading") return <p role="status">Checking session</p>;
  if (auth.status !== "authenticated") {
    return (
      <button
        type="button"
        onClick={() =>
          void auth.login({ email: userB.email, password: "password" }).catch(() => undefined)
        }
      >
        Sign in as User B
      </button>
    );
  }

  return (
    <>
      <p>Authenticated as {auth.user.username}</p>
      <button type="button" onClick={() => void auth.logout().catch(() => undefined)}>
        Sign out
      </button>
      <RepositoryBrowsePanel repositoryId="shared-repository" userId={auth.user.id} />
    </>
  );
}

function renderBrowseProbe() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  queryClients.push(queryClient);
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AuthProvider>
          <AuthenticatedBrowseProbe />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return queryClient;
}

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

beforeEach(() => {
  apiClient.setCsrfToken(null);
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  apiClient.setCsrfToken(null);
  vi.unstubAllGlobals();
  fetchMock.mockReset();
  for (const queryClient of queryClients.splice(0)) queryClient.clear();
});

describe("protected query identity boundary", () => {
  it("does not show user A's cached private browse data after logout and user B login", async () => {
    let activeUser = userA;
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) {
        return Promise.resolve(jsonResponse(userA, 200, { "X-CSRF-Token": "csrf-a" }));
      }
      if (url.endsWith("/api/v1/auth/logout")) {
        activeUser = userA;
        return Promise.resolve(jsonResponse({ status: "ok" }));
      }
      if (url.endsWith("/api/v1/auth/login")) {
        activeUser = userB;
        return Promise.resolve(jsonResponse(userB, 200, { "X-CSRF-Token": "csrf-b" }));
      }
      if (url.endsWith("/api/v1/repositories/shared-repository/refs")) {
        return activeUser.id === userA.id
          ? Promise.resolve(jsonResponse({ repository_id: "shared-repository", refs: [] }))
          : Promise.resolve(
              jsonResponse(
                { error: { code: "forbidden", message: "Repository access denied." } },
                403,
              ),
            );
      }
      if (url.endsWith("/api/v1/repositories/shared-repository/tree")) {
        return activeUser.id === userA.id
          ? Promise.resolve(
              jsonResponse({
                repository_id: "shared-repository",
                commit_id: "commit-a",
                path: "",
                entries: [
                  {
                    name: "A-private.txt",
                    type: "blob",
                    mode: "100644",
                    object_id: "blob-a",
                  },
                ],
              }),
            )
          : Promise.resolve(
              jsonResponse(
                { error: { code: "forbidden", message: "Repository access denied." } },
                403,
              ),
            );
      }
      if (url.includes("/api/v1/repositories/shared-repository/commits?")) {
        return activeUser.id === userA.id
          ? Promise.resolve(
              jsonResponse({
                repository_id: "shared-repository",
                commits: [],
                limit: 50,
                truncated: false,
              }),
            )
          : Promise.resolve(
              jsonResponse(
                { error: { code: "forbidden", message: "Repository access denied." } },
                403,
              ),
            );
      }
      if (url.includes("/api/v1/repositories/shared-repository/blob?")) {
        return activeUser.id === userA.id
          ? Promise.resolve(
              jsonResponse({
                repository_id: "shared-repository",
                commit_id: "commit-a",
                path: "A-private.txt",
                object_id: "blob-a",
                size: 25,
                is_binary: false,
                content: "private content for user A",
              }),
            )
          : Promise.resolve(
              jsonResponse(
                { error: { code: "forbidden", message: "Repository access denied." } },
                403,
              ),
            );
      }
      throw new Error(`Unexpected API request: ${url}`);
    });
    const user = userEvent.setup();
    const queryClient = renderBrowseProbe();
    const userATreeKey = protectedQueryKey(
      userA.id,
      "repository-browse",
      "shared-repository",
      "tree",
      "HEAD",
      "",
    );

    expect(await screen.findByText("Authenticated as user-a")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "A-private.txt" }));
    expect(await screen.findByText("private content for user A")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("button", { name: "Sign in as User B" })).toBeInTheDocument();
    expect(queryClient.getQueryData(userATreeKey)).toBeUndefined();
    await user.click(screen.getByRole("button", { name: "Sign in as User B" }));

    expect(await screen.findByText("Authenticated as user-b")).toBeInTheDocument();
    expect(await screen.findAllByText("Repository access denied.")).not.toHaveLength(0);
    expect(screen.queryByRole("button", { name: "A-private.txt" })).not.toBeInTheDocument();
    expect(screen.queryByText("private content for user A")).not.toBeInTheDocument();
  });

  it("cancels in-flight protected requests on logout and preserves public cache data", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    queryClients.push(queryClient);
    const userAKey = protectedQueryKey(userA.id, "repository-browse", "repo", "tree");
    const userBKey = protectedQueryKey(userB.id, "repository-browse", "repo", "tree");
    const pendingResult = deferred<string>();
    let requestStarted!: () => void;
    const started = new Promise<void>((resolve) => {
      requestStarted = resolve;
    });
    queryClient.setQueryData(["public", "landing-summary"], "public data");
    await transitionProtectedQueryIdentity(queryClient, userA.id);
    const request = queryClient
      .fetchQuery({
        queryKey: userAKey,
        queryFn: () => {
          requestStarted();
          return pendingResult.promise;
        },
      })
      .catch(() => undefined);
    await started;

    await transitionProtectedQueryIdentity(queryClient, null, true);
    clearPersonalRepositoryMutationState(queryClient, null);
    await transitionProtectedQueryIdentity(queryClient, userB.id);
    clearPersonalRepositoryMutationState(queryClient, userB.id);
    queryClient.setQueryData(userBKey, "user B data");
    pendingResult.resolve("late private data from user A");
    await request;

    expect(queryClient.getQueryData(userAKey)).toBeUndefined();
    expect(queryClient.getQueryData(userBKey)).toBe("user B data");
    expect(queryClient.getQueryData(["public", "landing-summary"])).toBe("public data");
  });
});
