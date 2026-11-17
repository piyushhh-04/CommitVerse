import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { apiClient } from "../api/client";
import type { PersonalRepository } from "../api/repositories";
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

function NavigationButton({ to, label }: { to: string; label: string }) {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => void navigate(to)}>
      {label}
    </button>
  );
}

function createRepository(index = 1): PersonalRepository {
  return {
    id: `6f577861-febc-4c87-8949-e920147114${String(index).padStart(2, "0")}`,
    name: `repository-${index}`,
    description: `Description ${index}`,
    visibility: index % 2 === 0 ? "public" : "private",
    created_at: "2026-11-15T10:00:00Z",
    updated_at: "2026-11-15T10:00:00Z",
  };
}

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function currentUserResponse(): Response {
  return jsonResponse(user, 200, { "X-CSRF-Token": "csrf-session" });
}

function emptyListResponse() {
  return jsonResponse({ items: [], total: 0, limit: 50, offset: 0 });
}

function renderAtPath(path: string, navigation?: { to: string; label: string }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  queryClients.push(queryClient);
  return render(
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[path]}>
          {navigation ? <NavigationButton {...navigation} /> : null}
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
  for (const queryClient of queryClients.splice(0)) queryClient.clear();
});

describe("personal repository pages", () => {
  it("shows loading and empty states with a clear create path", async () => {
    let resolveList!: (response: Response) => void;
    const pendingList = new Promise<Response>((resolve) => {
      resolveList = resolve;
    });
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) return Promise.resolve(currentUserResponse());
      if (url.includes("/api/v1/repositories?")) return pendingList;
      throw new Error(`Unexpected API request: ${url}`);
    });
    renderAtPath("/app/repositories");

    expect(await screen.findByRole("heading", { name: "Repositories" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Loading repositories");
    resolveList(emptyListResponse());

    expect(
      await screen.findByRole("heading", { name: "Your repositories will live here." }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create your first repository" })).toHaveAttribute(
      "href",
      "/app/repositories/new",
    );
    expect(
      screen.getByText(/Ready public repositories allow anonymous read-only API access/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/signed-in Hub web app/i)).toBeInTheDocument();
    expect(
      screen.getByText(/public repositories also allow read-only access through the API/i),
    ).toBeInTheDocument();
  });

  it("lists repositories and paginates using the backend offset", async () => {
    const firstPage = Array.from({ length: 50 }, (_, index) => createRepository(index + 1));
    const lastRepository = createRepository(51);
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) return Promise.resolve(currentUserResponse());
      if (url.endsWith("/api/v1/repositories?limit=50&offset=0")) {
        return Promise.resolve(jsonResponse({ items: firstPage, total: 51, limit: 50, offset: 0 }));
      }
      if (url.endsWith("/api/v1/repositories?limit=50&offset=50")) {
        return Promise.resolve(
          jsonResponse({ items: [lastRepository], total: 51, limit: 50, offset: 50 }),
        );
      }
      throw new Error(`Unexpected API request: ${url}`);
    });
    const userEventInstance = userEvent.setup();
    renderAtPath("/app/repositories");

    expect(
      await screen.findByRole("link", { name: "View repository repository-1" }),
    ).toHaveAttribute("href", `/app/repositories/${firstPage[0]?.id}`);
    expect(screen.getAllByText("private").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Updated/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await userEventInstance.click(screen.getByRole("button", { name: "Next" }));

    expect(
      await screen.findByRole("link", { name: "View repository repository-51" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Showing 51–51 of 51")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it("shows only the unavailable-page state when an empty later page has no repositories", async () => {
    const firstPage = Array.from({ length: 50 }, (_, index) => createRepository(index + 1));
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) return Promise.resolve(currentUserResponse());
      if (url.endsWith("/api/v1/repositories?limit=50&offset=0")) {
        return Promise.resolve(jsonResponse({ items: firstPage, total: 51, limit: 50, offset: 0 }));
      }
      if (url.endsWith("/api/v1/repositories?limit=50&offset=50")) {
        return Promise.resolve(jsonResponse({ items: [], total: 0, limit: 50, offset: 50 }));
      }
      throw new Error(`Unexpected API request: ${url}`);
    });
    const userEventInstance = userEvent.setup();
    renderAtPath("/app/repositories");

    await userEventInstance.click(await screen.findByRole("button", { name: "Next" }));

    expect(
      await screen.findByRole("heading", { name: "No repositories on this page." }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Your repositories will live here." }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back to the first page" })).toBeInTheDocument();
  });

  it("offers a retry when the repository list fails", async () => {
    let listRequests = 0;
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) return Promise.resolve(currentUserResponse());
      if (url.includes("/api/v1/repositories?")) {
        listRequests += 1;
        return Promise.resolve(
          listRequests === 1
            ? jsonResponse(
                {
                  error: {
                    code: "repository_unavailable",
                    message: "Repository list unavailable.",
                  },
                  request_id: "repository-list-error",
                },
                503,
              )
            : emptyListResponse(),
        );
      }
      throw new Error(`Unexpected API request: ${url}`);
    });
    const userEventInstance = userEvent.setup();
    renderAtPath("/app/repositories");

    expect(await screen.findByRole("alert")).toHaveTextContent("Repository list unavailable.");
    await userEventInstance.click(screen.getByRole("button", { name: "Try again" }));
    expect(
      await screen.findByRole("heading", { name: "Your repositories will live here." }),
    ).toBeInTheDocument();
    expect(listRequests).toBe(2);
  });

  it("validates creation, defaults to private, and navigates to the created details", async () => {
    const created = {
      ...createRepository(),
      name: "new-repository",
      description: null,
      visibility: "private" as const,
    };
    const requestBodies: unknown[] = [];
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) return currentUserResponse();
      if (url.endsWith("/api/v1/repositories") && init?.method === "POST") {
        requestBodies.push(JSON.parse(String(init.body)));
        return jsonResponse(created, 201);
      }
      if (url.endsWith(`/api/v1/repositories/${created.id}`)) return jsonResponse(created);
      throw new Error(`Unexpected API request: ${url}`);
    });
    const userEventInstance = userEvent.setup();
    renderAtPath("/app/repositories/new");

    expect(await screen.findByRole("heading", { name: "New repository" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Private/ })).toBeChecked();
    expect(
      screen.getByText(/Ready public repositories allow anonymous read-only API access/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/The Hub web app requires sign-in/i)).toBeInTheDocument();
    await userEventInstance.type(screen.getByLabelText("Repository name"), "../invalid");
    await userEventInstance.click(screen.getByRole("button", { name: "Create repository" }));
    expect(screen.getByText(/start with a letter or number/i)).toBeInTheDocument();
    expect(requestBodies).toHaveLength(0);

    await userEventInstance.clear(screen.getByLabelText("Repository name"));
    await userEventInstance.type(screen.getByLabelText("Repository name"), " New-Repository ");
    await userEventInstance.click(screen.getByRole("button", { name: "Create repository" }));

    expect(await screen.findByRole("heading", { name: "new-repository" })).toHaveFocus();
    expect(requestBodies).toEqual([
      { name: "new-repository", description: null, visibility: "private" },
    ]);
  });

  it("surfaces duplicate-name conflicts without navigating", async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) return currentUserResponse();
      if (url.endsWith("/api/v1/repositories") && init?.method === "POST") {
        return jsonResponse(
          {
            error: { code: "repository_conflict", message: "Repository name is already in use." },
            request_id: "repository-conflict",
          },
          409,
        );
      }
      throw new Error(`Unexpected API request: ${url}`);
    });
    const userEventInstance = userEvent.setup();
    renderAtPath("/app/repositories/new");

    expect(await screen.findByRole("heading", { name: "New repository" })).toBeInTheDocument();
    await userEventInstance.type(screen.getByLabelText("Repository name"), "existing");
    await userEventInstance.click(screen.getByRole("button", { name: "Create repository" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Choose a different name.");
    expect(screen.getByText("Reference: repository-conflict")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "New repository" })).toBeInTheDocument();
  });

  it("updates only changed metadata and sends null to clear a description", async () => {
    const original = createRepository();
    const updated = {
      ...original,
      name: "renamed-repository",
      description: null,
      visibility: "public" as const,
    };
    let patchBody: unknown;
    let currentRepository = original;
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) return currentUserResponse();
      if (url.endsWith(`/api/v1/repositories/${original.id}`) && init?.method === "PATCH") {
        patchBody = JSON.parse(String(init.body));
        currentRepository = updated;
        return jsonResponse(updated);
      }
      if (url.endsWith(`/api/v1/repositories/${original.id}`))
        return jsonResponse(currentRepository);
      throw new Error(`Unexpected API request: ${url}`);
    });
    const userEventInstance = userEvent.setup();
    renderAtPath(`/app/repositories/${original.id}`);

    expect(await screen.findByRole("heading", { name: original.name })).toBeInTheDocument();
    expect(screen.getByText(/Browsing in the Hub web app requires sign-in/i)).toBeInTheDocument();
    await userEventInstance.clear(screen.getByLabelText("Repository name"));
    await userEventInstance.type(screen.getByLabelText("Repository name"), updated.name);
    await userEventInstance.clear(screen.getByLabelText("Description (optional)"));
    await userEventInstance.click(screen.getByRole("radio", { name: /Public/ }));
    await userEventInstance.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Changes saved.");
    expect(patchBody).toEqual({
      name: updated.name,
      description: null,
      visibility: "public",
    });
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: updated.name })).toBeInTheDocument(),
    );
  });

  it("keeps the delete ID available for retry after a failed cleanup", async () => {
    const repository = createRepository();
    let deleteRequests = 0;
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) return currentUserResponse();
      if (url.endsWith(`/api/v1/repositories/${repository.id}`) && init?.method === "DELETE") {
        deleteRequests += 1;
        return deleteRequests === 1
          ? jsonResponse(
              {
                error: {
                  code: "repository_unavailable",
                  message:
                    "Repository deletion is pending safe storage cleanup; retry the request.",
                },
                request_id: "repository-delete-pending",
              },
              503,
            )
          : new Response(null, { status: 204 });
      }
      if (url.endsWith(`/api/v1/repositories/${repository.id}`)) return jsonResponse(repository);
      if (url.includes("/api/v1/repositories?")) return emptyListResponse();
      throw new Error(`Unexpected API request: ${url}`);
    });
    const userEventInstance = userEvent.setup();
    renderAtPath(`/app/repositories/${repository.id}`);

    expect(await screen.findByRole("heading", { name: repository.name })).toBeInTheDocument();
    const deleteButton = screen.getByRole("button", { name: "Delete repository" });
    await userEventInstance.click(deleteButton);
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    await userEventInstance.keyboard("{Escape}");
    expect(deleteButton).toHaveFocus();

    await userEventInstance.click(deleteButton);
    await userEventInstance.click(screen.getByRole("button", { name: "Confirm deletion" }));
    expect(
      await screen.findByText(
        "The deletion may still be pending. Retry here before leaving this page.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry deletion" })).toBeInTheDocument();
    expect(
      screen.getByText(/reloading may make a pending deletion unavailable/i),
    ).toBeInTheDocument();

    await userEventInstance.click(screen.getByRole("button", { name: "Retry deletion" }));
    expect(await screen.findByRole("heading", { name: "Repositories" })).toHaveFocus();
    expect(deleteRequests).toBe(2);
  });

  it("does not carry a failed delete confirmation or retry state to another repository", async () => {
    const repositoryA = createRepository(1);
    const repositoryB = createRepository(2);
    const deletePaths: string[] = [];
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) return currentUserResponse();
      if (init?.method === "DELETE") {
        deletePaths.push(url);
        return jsonResponse(
          {
            error: {
              code: "repository_unavailable",
              message: "Repository deletion is pending safe storage cleanup; retry the request.",
            },
            request_id: "repository-delete-pending",
          },
          503,
        );
      }
      if (url.endsWith(`/api/v1/repositories/${repositoryA.id}`)) return jsonResponse(repositoryA);
      if (url.endsWith(`/api/v1/repositories/${repositoryB.id}`)) return jsonResponse(repositoryB);
      if (url.includes("/api/v1/repositories?")) return emptyListResponse();
      throw new Error(`Unexpected API request: ${url}`);
    });
    const userEventInstance = userEvent.setup();
    renderAtPath(`/app/repositories/${repositoryA.id}`, {
      to: `/app/repositories/${repositoryB.id}`,
      label: "Open repository B",
    });

    expect(await screen.findByRole("heading", { name: repositoryA.name })).toBeInTheDocument();
    await userEventInstance.click(screen.getByRole("button", { name: "Delete repository" }));
    await userEventInstance.click(screen.getByRole("button", { name: "Confirm deletion" }));
    expect(await screen.findByRole("button", { name: "Retry deletion" })).toBeInTheDocument();

    await userEventInstance.click(screen.getByRole("button", { name: "Open repository B" }));

    expect(await screen.findByRole("heading", { name: repositoryB.name })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry deletion" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: `Delete ${repositoryB.name}?` }),
    ).not.toBeInTheDocument();
    expect(deletePaths).toEqual([`/api/v1/repositories/${repositoryA.id}`]);

    await userEventInstance.click(screen.getByRole("button", { name: "Delete repository" }));
    expect(screen.getByRole("button", { name: "Confirm deletion" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry deletion" })).not.toBeInTheDocument();
    expect(deletePaths).toEqual([`/api/v1/repositories/${repositoryA.id}`]);
  });

  it("handles repositories that are missing or inaccessible", async () => {
    const repositoryId = createRepository().id;
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) return Promise.resolve(currentUserResponse());
      if (url.endsWith(`/api/v1/repositories/${repositoryId}`)) {
        return Promise.resolve(
          jsonResponse(
            {
              error: { code: "repository_not_found", message: "Repository not found." },
              request_id: "repository-not-found",
            },
            404,
          ),
        );
      }
      throw new Error(`Unexpected API request: ${url}`);
    });
    renderAtPath(`/app/repositories/${repositoryId}`);

    expect(
      await screen.findByRole("heading", { name: "Repository unavailable" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("It may have been deleted");
    expect(screen.getByRole("link", { name: "Back to repositories" })).toBeInTheDocument();
  });
});
