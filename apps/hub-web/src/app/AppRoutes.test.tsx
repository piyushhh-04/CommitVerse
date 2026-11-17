import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { apiClient } from "../api/client";
import { ThemeProvider } from "../theme/ThemeProvider";
import { AppRoutes } from "./AppRoutes";

const fetchMock = vi.fn<typeof fetch>();

function renderAtPath(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes />
        </MemoryRouter>
      </QueryClientProvider>
    </ThemeProvider>,
  );
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

describe("application routes", () => {
  it("keeps the public landing page outside session bootstrap", () => {
    renderAtPath("/");

    expect(screen.getByRole("heading", { name: /Version control/ })).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("browses public repositories anonymously without sending session cookies", async () => {
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/repositories/public-repo/refs")) {
        return new Response(JSON.stringify({ repository_id: "public-repo", refs: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.endsWith("/repositories/public-repo/tree")) {
        return new Response(
          JSON.stringify({
            repository_id: "public-repo",
            commit_id: null,
            path: "",
            entries: [],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url.endsWith("/repositories/public-repo/commits?limit=50")) {
        return new Response(
          JSON.stringify({
            repository_id: "public-repo",
            commits: [],
            limit: 50,
            truncated: false,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      throw new Error(`Unexpected API request: ${url}`);
    });

    renderAtPath("/browse/public-repo");

    expect(await screen.findByText(/anonymous, read-only API requests/i)).toBeInTheDocument();
    await screen.findByText("Empty repository");
    expect(fetchMock).toHaveBeenCalledTimes(3);
    for (const [, options] of fetchMock.mock.calls) {
      expect(options?.credentials).toBe("omit");
    }
    expect(fetchMock).not.toHaveBeenCalledWith("/api/v1/me", expect.anything());
  });

  it("accepts a repository invitation and opens the authenticated browser", async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) {
        return new Response(
          JSON.stringify({
            id: "user-1",
            email: "developer@example.test",
            username: "developer",
            display_name: "Developer",
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json", "X-CSRF-Token": "csrf-session" },
          },
        );
      }
      if (
        url.endsWith("/api/v1/repositories/invitations/invitation-token/accept") &&
        init?.method === "POST"
      ) {
        return new Response(JSON.stringify({ repository_id: "invited-repo", role: "reader" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.endsWith("/api/v1/repositories/invited-repo/refs")) {
        return new Response(JSON.stringify({ repository_id: "invited-repo", refs: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.endsWith("/api/v1/repositories/invited-repo/tree")) {
        return new Response(
          JSON.stringify({
            repository_id: "invited-repo",
            commit_id: null,
            path: "",
            entries: [],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url.endsWith("/api/v1/repositories/invited-repo/commits?limit=50")) {
        return new Response(
          JSON.stringify({
            repository_id: "invited-repo",
            commits: [],
            limit: 50,
            truncated: false,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      throw new Error(`Unexpected API request: ${url}`);
    });
    const user = userEvent.setup();
    renderAtPath("/app/repositories/invitations/accept");

    await user.type(
      await screen.findByRole("textbox", { name: "Repository invitation token" }),
      "invitation-token",
    );
    await user.click(screen.getByRole("button", { name: "Accept invitation" }));

    expect(await screen.findByText(/Repository ID:/)).toHaveTextContent("invited-repo");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/repositories/invitations/invitation-token/accept",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("redirects an anonymous visitor from a protected route to sign in", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error: { code: "unauthenticated", message: "Not signed in." },
          request_id: "req-anonymous",
        }),
        { status: 401, headers: { "Content-Type": "application/json" } },
      ),
    );
    renderAtPath("/app/organizations/org-1/members");

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("renders a protected route only after restoring an authenticated session", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "user-1",
            email: "dev@example.test",
            username: "dev",
            display_name: "Developer",
          }),
          {
            status: 200,
            headers: {
              "Content-Type": "application/json",
              "X-CSRF-Token": "csrf-session",
            },
          },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ items: [], total: 0, limit: 50, offset: 0 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    renderAtPath("/app/repositories");

    expect(await screen.findByRole("heading", { name: "Repositories" })).toBeInTheDocument();
  });

  it("shows a recoverable session error instead of redirecting on API failure", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error: { code: "service_unavailable", message: "Try again later." },
          request_id: "req-unavailable",
        }),
        { status: 503, headers: { "Content-Type": "application/json" } },
      ),
    );
    renderAtPath("/app");

    expect(
      await screen.findByRole("heading", { name: "We could not verify your session." }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sign in" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
