import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";
import { apiClient } from "../api/client";
import { AppRoutes } from "../app/AppRoutes";
import { ThemeProvider } from "../theme/ThemeProvider";

const userA = {
  id: "user-a",
  email: "user-a@example.test",
  username: "user-a",
  display_name: "User A",
};
const userB = {
  id: "user-b",
  email: "user-b@example.test",
  username: "user-b",
  display_name: "User B",
};
const fetchMock = vi.fn<typeof fetch>();
const queryClients: QueryClient[] = [];

type TestUser = ReturnType<typeof userEvent.setup>;

interface MutationScenario {
  name: string;
  path: string;
  formHeading: string;
  endpoint: string;
  method?: "POST" | "DELETE";
  destination: string;
  result: unknown;
  getResponses?: Record<string, unknown>;
  submit: (user: TestUser) => Promise<void>;
}

const mutationScenarios: MutationScenario[] = [
  {
    name: "organization creation",
    path: "/app/organizations/new",
    formHeading: "New organization",
    endpoint: "/api/v1/organizations",
    destination: "/app/organizations/org-created-by-a",
    result: {
      id: "org-created-by-a",
      slug: "user-a-org",
      name: "User A organization",
      state: "active",
      role: "owner",
      created_at: "2026-11-15T10:00:00Z",
      updated_at: "2026-11-15T10:00:00Z",
    },
    submit: async (user) => {
      await user.type(screen.getByLabelText("Organization slug"), "user-a-org");
      await user.type(screen.getByLabelText("Organization name"), "User A organization");
      await user.click(screen.getByRole("button", { name: "Create organization" }));
    },
  },
  {
    name: "organization repository creation",
    path: "/app/organizations/org-a/repositories/new",
    formHeading: "New repository",
    endpoint: "/api/v1/organizations/org-a/repositories",
    destination: "/app/organizations/org-a/repositories/repository-created-by-a",
    result: {
      id: "repository-created-by-a",
      name: "user-a-repository",
      description: null,
      visibility: "private",
      created_at: "2026-11-15T10:00:00Z",
      updated_at: "2026-11-15T10:00:00Z",
    },
    submit: async (user) => {
      await user.type(screen.getByLabelText("Repository name"), "user-a-repository");
      await user.click(screen.getByRole("button", { name: "Create repository" }));
    },
  },
  {
    name: "invitation acceptance",
    path: "/app/invitations/accept",
    formHeading: "Accept an invitation",
    endpoint: "/api/v1/invitations/invitation-token/accept",
    destination: "/app/organizations/org-joined-by-a",
    result: { organization_id: "org-joined-by-a", role: "member" },
    submit: async (user) => {
      await user.type(
        screen.getByRole("textbox", { name: "Invitation token" }),
        "invitation-token",
      );
      await user.click(screen.getByRole("button", { name: "Accept invitation" }));
    },
  },
  {
    name: "organization leave",
    path: "/app/organizations/org-a",
    formHeading: "Organization A",
    endpoint: "/api/v1/organizations/org-a/leave",
    destination: "/app/organizations",
    result: {},
    getResponses: {
      "/api/v1/organizations/org-a": {
        id: "org-a",
        slug: "organization-a",
        name: "Organization A",
        state: "active",
        role: "member",
        created_at: "2026-11-15T10:00:00Z",
        updated_at: "2026-11-15T10:00:00Z",
      },
      "/api/v1/organizations/org-a/members?limit=100&offset=0": {
        items: [],
        total: 0,
        limit: 100,
        offset: 0,
      },
    },
    submit: async (user) => {
      await user.click(screen.getByRole("button", { name: "Leave organization" }));
      await user.click(screen.getByRole("button", { name: "Confirm leave" }));
    },
  },
  {
    name: "organization repository deletion",
    path: "/app/organizations/org-a/repositories/repository-a",
    formHeading: "repository-a",
    endpoint: "/api/v1/organizations/org-a/repositories/repository-a",
    method: "DELETE",
    destination: "/app/organizations/org-a/repositories",
    result: {},
    getResponses: {
      "/api/v1/organizations/org-a/repositories/repository-a": {
        id: "repository-a",
        name: "repository-a",
        description: null,
        visibility: "private",
        created_at: "2026-11-15T10:00:00Z",
        updated_at: "2026-11-15T10:00:00Z",
      },
    },
    submit: async (user) => {
      await user.click(screen.getByRole("button", { name: "Delete repository" }));
      await user.click(screen.getByRole("button", { name: "Confirm deletion" }));
    },
  },
];

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="current-path">{location.pathname}</output>;
}

function renderAtPath(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  queryClients.push(queryClient);
  return render(
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[path]}>
          <LocationProbe />
          <AppRoutes />
        </MemoryRouter>
      </QueryClientProvider>
    </ThemeProvider>,
  );
}

async function completeMutation(response: unknown) {
  await act(async () => {
    resolveMutation(jsonResponse(response));
    await new Promise((resolve) => setTimeout(resolve, 25));
  });
}

let resolveMutation!: (response: Response) => void;
let mutationStarted!: () => void;
let mutationResponse: Promise<Response>;
let mutationRequestStarted: Promise<void>;

beforeEach(() => {
  apiClient.setCsrfToken(null);
  mutationResponse = new Promise<Response>((resolve) => {
    resolveMutation = resolve;
  });
  mutationRequestStarted = new Promise<void>((resolve) => {
    mutationStarted = resolve;
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  apiClient.setCsrfToken(null);
  vi.unstubAllGlobals();
  fetchMock.mockReset();
  for (const queryClient of queryClients.splice(0)) queryClient.clear();
});

describe.each(mutationScenarios)("$name identity safety", (scenario) => {
  async function startPendingMutation() {
    let activeUser = userA;
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/api/v1/me")) {
        return Promise.resolve(
          jsonResponse(activeUser, 200, { "X-CSRF-Token": `csrf-${activeUser.id}` }),
        );
      }
      if (url.endsWith("/api/v1/auth/logout")) {
        return Promise.resolve(jsonResponse({ status: "ok" }));
      }
      if (url.endsWith("/api/v1/auth/login")) {
        activeUser = userB;
        return Promise.resolve(jsonResponse(userB, 200, { "X-CSRF-Token": "csrf-user-b" }));
      }
      if (url.endsWith(scenario.endpoint) && method === (scenario.method ?? "POST")) {
        mutationStarted();
        return mutationResponse;
      }
      if (method === "GET") {
        const response = scenario.getResponses?.[url];
        if (response !== undefined) {
          return Promise.resolve(
            activeUser.id === userA.id
              ? jsonResponse(response)
              : jsonResponse(
                  { error: { code: "forbidden", message: "Repository access denied." } },
                  403,
                ),
          );
        }
        return Promise.resolve(jsonResponse({}, 404));
      }
      throw new Error(`Unexpected API request: ${method} ${url}`);
    });

    const user = userEvent.setup();
    renderAtPath(scenario.path);
    expect(await screen.findByRole("heading", { name: scenario.formHeading })).toBeInTheDocument();
    await scenario.submit(user);
    await mutationRequestStarted;
    return user;
  }

  it("does not navigate User B when User A's pending mutation completes after an account switch", async () => {
    const user = await startPendingMutation();
    await user.click(screen.getByRole("button", { name: "Sign out" }));

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Email address"), userB.email);
    await user.type(screen.getByLabelText("Password"), "user-b-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("User B")).toBeInTheDocument();
    expect(screen.getByTestId("current-path")).toHaveTextContent(scenario.path);
    await completeMutation(scenario.result);

    expect(screen.getByTestId("current-path").textContent).toBe(scenario.path);
  });

  it("preserves successful navigation when the initiating identity remains active", async () => {
    await startPendingMutation();
    await completeMutation(scenario.result);

    expect(await screen.findByTestId("current-path")).toHaveTextContent(scenario.destination);
    expect(screen.queryByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });
});
