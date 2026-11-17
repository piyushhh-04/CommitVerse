import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { apiClient } from "../api/client";
import { AppRoutes } from "../app/AppRoutes";
import { ThemeProvider } from "../theme/ThemeProvider";

const user = {
  id: "user-1",
  email: "developer@example.test",
  username: "developer",
  display_name: "Developer",
};
const fetchMock = vi.fn<typeof fetch>();
const queryClients: QueryClient[] = [];

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  queryClients.push(queryClient);
  return render(
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/app"]}>
          <AppRoutes />
        </MemoryRouter>
      </QueryClientProvider>
    </ThemeProvider>,
  );
}

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function currentUserResponse() {
  return jsonResponse(user, 200, { "X-CSRF-Token": "csrf-session" });
}

function emptyRepositoriesResponse() {
  return jsonResponse({ items: [], total: 0, limit: 4, offset: 0 });
}

function emptyOrganizationsResponse() {
  return jsonResponse({ items: [], total: 0, limit: 50, offset: 0 });
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

describe("workspace dashboard", () => {
  it("announces loading while repository and organization summaries are pending", async () => {
    const repositories = deferred<Response>();
    const organizations = deferred<Response>();
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) return Promise.resolve(currentUserResponse());
      if (url.includes("/api/v1/repositories?")) return repositories.promise;
      if (url.includes("/api/v1/organizations?")) return organizations.promise;
      throw new Error(`Unexpected API request: ${url}`);
    });

    renderDashboard();

    expect(await screen.findByRole("heading", { name: "Welcome, Developer" })).toBeInTheDocument();
    expect(screen.getByText("Loading your repositories…")).toBeInTheDocument();
    expect(screen.getByText("Loading your organizations…")).toBeInTheDocument();
    repositories.resolve(emptyRepositoriesResponse());
    organizations.resolve(emptyOrganizationsResponse());
    expect(await screen.findByText("You have not created a repository yet.")).toBeInTheDocument();
    expect(await screen.findByText("You are not part of an organization yet.")).toBeInTheDocument();
  });

  it("shows repository and organization summaries from the API", async () => {
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) return Promise.resolve(currentUserResponse());
      if (url.includes("/api/v1/repositories?")) {
        return Promise.resolve(
          jsonResponse({
            items: [
              {
                id: "repo-1",
                name: "commitverse-core",
                description: "Core engine",
                visibility: "private",
                created_at: "2026-11-15T10:00:00Z",
                updated_at: "2026-11-15T10:00:00Z",
              },
            ],
            total: 1,
            limit: 4,
            offset: 0,
          }),
        );
      }
      if (url.includes("/api/v1/organizations?")) {
        return Promise.resolve(
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
      }
      throw new Error(`Unexpected API request: ${url}`);
    });

    renderDashboard();

    expect(await screen.findByRole("link", { name: "commitverse-core" })).toHaveAttribute(
      "href",
      "/app/repositories/repo-1",
    );
    expect(await screen.findByRole("link", { name: "CommitVerse" })).toHaveAttribute(
      "href",
      "/app/organizations/org-1",
    );
    expect(screen.getByRole("link", { name: "View all repositories" })).toHaveAttribute(
      "href",
      "/app/repositories",
    );
    expect(screen.getByRole("link", { name: "View all organizations" })).toHaveAttribute(
      "href",
      "/app/organizations",
    );
  });

  it("offers useful create and invitation paths when both lists are empty", async () => {
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) return Promise.resolve(currentUserResponse());
      if (url.includes("/api/v1/repositories?"))
        return Promise.resolve(emptyRepositoriesResponse());
      if (url.includes("/api/v1/organizations?")) {
        return Promise.resolve(emptyOrganizationsResponse());
      }
      throw new Error(`Unexpected API request: ${url}`);
    });

    renderDashboard();

    expect(await screen.findByText("You have not created a repository yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create your first repository" })).toHaveAttribute(
      "href",
      "/app/repositories/new",
    );
    expect(await screen.findByText("You are not part of an organization yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create an organization" })).toHaveAttribute(
      "href",
      "/app/organizations/new",
    );
    expect(screen.getByRole("link", { name: "Accept an invitation" })).toHaveAttribute(
      "href",
      "/app/invitations/accept",
    );
  });

  it("shows independent API errors and retries each summary", async () => {
    let repositoryRequests = 0;
    let organizationRequests = 0;
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) return Promise.resolve(currentUserResponse());
      if (url.includes("/api/v1/repositories?")) {
        repositoryRequests += 1;
        return Promise.resolve(
          repositoryRequests === 1
            ? jsonResponse(
                { error: { code: "unavailable", message: "Repository service unavailable." } },
                503,
              )
            : emptyRepositoriesResponse(),
        );
      }
      if (url.includes("/api/v1/organizations?")) {
        organizationRequests += 1;
        return Promise.resolve(
          organizationRequests === 1
            ? jsonResponse(
                { error: { code: "unavailable", message: "Organization service unavailable." } },
                503,
              )
            : emptyOrganizationsResponse(),
        );
      }
      throw new Error(`Unexpected API request: ${url}`);
    });
    const user = userEvent.setup();

    renderDashboard();

    expect(await screen.findByRole("heading", { name: "Welcome, Developer" })).toBeInTheDocument();
    const repositorySection = screen.getByRole("region", { name: "Repositories" });
    const organizationSection = screen.getByRole("region", { name: "Organizations" });
    expect(await within(repositorySection).findByRole("alert")).toHaveTextContent(
      "Repository service unavailable.",
    );
    expect(await within(organizationSection).findByRole("alert")).toHaveTextContent(
      "Organization service unavailable.",
    );
    await user.click(within(repositorySection).getByRole("button", { name: "Try again" }));
    await user.click(within(organizationSection).getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("You have not created a repository yet.")).toBeInTheDocument();
    expect(await screen.findByText("You are not part of an organization yet.")).toBeInTheDocument();
    expect(repositoryRequests).toBe(2);
    expect(organizationRequests).toBe(2);
  });
});
