import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { apiClient } from "../api/client";
import { AppRoutes } from "../app/AppRoutes";
import { ThemeProvider } from "../theme/ThemeProvider";

const fetchMock = vi.fn<typeof fetch>();

function renderAtPath(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
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

function jsonResponse(body: unknown, status = 200, extraHeaders: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...extraHeaders },
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

describe("organization pages", () => {
  it("loads the authenticated organization list from the Hub API", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(
          { id: "user-1", email: "dev@example.test", username: "dev", display_name: "Developer" },
          200,
          { "X-CSRF-Token": "csrf-session" },
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          items: [
            {
              id: "org-1",
              slug: "commitverse",
              name: "CommitVerse",
              state: "active",
              role: "owner",
              created_at: "2026-11-15T10:00:00Z",
              updated_at: "2026-11-15T10:00:00Z",
            },
          ],
          total: 1,
          limit: 50,
          offset: 0,
        }),
      );

    renderAtPath("/app/organizations");

    expect(await screen.findByRole("link", { name: "CommitVerse" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New organization" })).toHaveAttribute(
      "href",
      "/app/organizations/new",
    );
  });

  it("paginates organization results using the backend offset contract", async () => {
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) {
        return jsonResponse(
          { id: "user-1", email: "dev@example.test", username: "dev", display_name: "Developer" },
          200,
          { "X-CSRF-Token": "csrf-session" },
        );
      }
      if (url.endsWith("/api/v1/organizations?limit=50&offset=0")) {
        return jsonResponse({
          items: [
            {
              id: "org-1",
              slug: "first-org",
              name: "First organization",
              state: "active",
              role: "owner",
              created_at: "2026-11-15T10:00:00Z",
              updated_at: "2026-11-15T10:00:00Z",
            },
          ],
          total: 51,
          limit: 50,
          offset: 0,
        });
      }
      if (url.endsWith("/api/v1/organizations?limit=50&offset=50")) {
        return jsonResponse({
          items: [
            {
              id: "org-51",
              slug: "last-org",
              name: "Last organization",
              state: "active",
              role: "member",
              created_at: "2026-11-15T10:00:00Z",
              updated_at: "2026-11-15T10:00:00Z",
            },
          ],
          total: 51,
          limit: 50,
          offset: 50,
        });
      }
      throw new Error(`Unexpected API request: ${url}`);
    });

    const user = userEvent.setup();
    renderAtPath("/app/organizations");

    expect(await screen.findByRole("link", { name: "First organization" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByRole("link", { name: "Last organization" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/organizations?limit=50&offset=50",
      expect.any(Object),
    );
  });

  it("limits organization administrator controls to the backend's member-only policy", async () => {
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) {
        return jsonResponse(
          {
            id: "admin-1",
            email: "admin@example.test",
            username: "admin",
            display_name: "Administrator",
          },
          200,
          { "X-CSRF-Token": "csrf-session" },
        );
      }
      if (url.endsWith("/api/v1/organizations/org-1")) {
        return jsonResponse({
          id: "org-1",
          slug: "example",
          name: "Example organization",
          state: "active",
          role: "admin",
          created_at: "2026-11-15T10:00:00Z",
          updated_at: "2026-11-15T10:00:00Z",
        });
      }
      if (url.endsWith("/api/v1/organizations/org-1/members?limit=100&offset=0")) {
        return jsonResponse({
          items: [
            {
              organization_id: "org-1",
              user_id: "admin-2",
              role: "admin",
              joined_at: "2026-11-15T10:00:00Z",
            },
            {
              organization_id: "org-1",
              user_id: "member-1",
              role: "member",
              joined_at: "2026-11-15T10:00:00Z",
            },
          ],
          total: 2,
          limit: 100,
          offset: 0,
        });
      }
      if (url.endsWith("/api/v1/organizations/org-1/invitations?limit=100&offset=0")) {
        return jsonResponse({ items: [], total: 0, limit: 100, offset: 0 });
      }
      throw new Error(`Unexpected API request: ${url}`);
    });

    renderAtPath("/app/organizations/org-1");

    expect(
      await screen.findByRole("heading", { name: "Example organization" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Member role" })).toHaveValue("member");
    expect(screen.queryByRole("option", { name: "Admin" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Make member" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Make admin" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Remove" })).toHaveLength(1);
    expect(screen.getByRole("combobox", { name: "Invitation role" })).toHaveValue("member");
  });

  it("offers direct access management for organization-owned repositories", async () => {
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) {
        return jsonResponse(
          { id: "owner-1", email: "owner@example.test", username: "owner", display_name: "Owner" },
          200,
          { "X-CSRF-Token": "csrf-session" },
        );
      }
      if (url.endsWith("/api/v1/organizations/org-1/repositories/repo-1")) {
        return jsonResponse({
          id: "repo-1",
          name: "Shared project",
          description: null,
          visibility: "private",
          created_at: "2026-11-15T10:00:00Z",
          updated_at: "2026-11-15T10:00:00Z",
        });
      }
      if (url.endsWith("/api/v1/repositories/repo-1/refs")) {
        return jsonResponse({ repository_id: "repo-1", refs: [] });
      }
      if (url.endsWith("/api/v1/repositories/repo-1/tree")) {
        return jsonResponse({
          repository_id: "repo-1",
          commit_id: null,
          path: "",
          entries: [],
        });
      }
      if (url.endsWith("/api/v1/repositories/repo-1/commits?limit=50")) {
        return jsonResponse({
          repository_id: "repo-1",
          commits: [],
          limit: 50,
          truncated: false,
        });
      }
      if (url.endsWith("/api/v1/repositories/repo-1/permissions")) {
        return jsonResponse([]);
      }
      if (url.endsWith("/api/v1/repositories/repo-1/invitations?limit=100&offset=0")) {
        return jsonResponse({ items: [], total: 0, limit: 100, offset: 0 });
      }
      throw new Error(`Unexpected API request: ${url}`);
    });

    renderAtPath("/app/organizations/org-1/repositories/repo-1");

    expect(await screen.findByRole("heading", { name: "Repository access" })).toBeInTheDocument();
    expect(await screen.findByText("No direct collaborators have access yet.")).toBeInTheDocument();
    expect(screen.getByText("No pending repository invitations.")).toBeInTheDocument();
  });
});
