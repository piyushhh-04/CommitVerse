import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { apiClient } from "../api/client";
import { AppRoutes } from "../app/AppRoutes";
import { ThemeProvider } from "../theme/ThemeProvider";

const fetchMock = vi.fn<typeof fetch>();
const user = {
  id: "user-1",
  email: "developer@example.test",
  username: "developer",
  display_name: "Developer",
  bio: "A builder.",
};
const anotherUser = {
  id: "user-2",
  email: "another@example.test",
  username: "another",
  display_name: "Another Developer",
  bio: null,
};

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

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/app/settings/profile"]}>
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

describe("profile settings", () => {
  it("loads and saves the authenticated profile through the API", async () => {
    const updated = {
      ...user,
      username: "updated-user",
      display_name: "Updated User",
      bio: "A more focused builder.",
    };
    let updateBody: unknown;
    let logoutCsrfToken: string | null = null;
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me") && init?.method === "PATCH") {
        updateBody = JSON.parse(String(init.body));
        return jsonResponse(updated);
      }
      if (url.endsWith("/api/v1/me")) return jsonResponse(user, 200, { "X-CSRF-Token": "csrf" });
      if (url.endsWith("/api/v1/auth/logout")) {
        logoutCsrfToken = new Headers(init?.headers).get("X-CSRF-Token");
        return jsonResponse({ status: "ok" });
      }
      throw new Error(`Unexpected API request: ${url}`);
    });

    const userEventInstance = userEvent.setup();
    renderPage();
    expect(await screen.findByRole("heading", { name: "Profile settings" })).toBeInTheDocument();
    expect(screen.getByLabelText("Username")).toHaveValue("developer");

    await userEventInstance.clear(screen.getByLabelText("Username"));
    await userEventInstance.type(screen.getByLabelText("Username"), "updated-user");
    await userEventInstance.clear(screen.getByLabelText("Display name"));
    await userEventInstance.type(screen.getByLabelText("Display name"), "Updated User");
    await userEventInstance.clear(screen.getByLabelText(/Bio/));
    await userEventInstance.type(screen.getByLabelText(/Bio/), "A more focused builder.");
    await userEventInstance.click(screen.getByRole("button", { name: "Save profile" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Profile saved.");
    expect(updateBody).toEqual({
      username: "updated-user",
      display_name: "Updated User",
      bio: "A more focused builder.",
    });
    expect(apiClient.hasCsrfToken).toBe(true);

    await userEventInstance.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(logoutCsrfToken).toBe("csrf");
  });

  it.each([
    {
      scenario: "a different user",
      nextUser: anotherUser,
      nextCsrfToken: "csrf-user-b",
    },
    {
      scenario: "the same user after relogin",
      nextUser: { ...user, display_name: "Current Session Developer" },
      nextCsrfToken: "csrf-new-session",
    },
  ])("ignores an old profile response after $scenario", async ({ nextUser, nextCsrfToken }) => {
    const pendingUpdate = deferred<Response>();
    let profileUpdateStarted!: () => void;
    const profileRequestStarted = new Promise<void>((resolve) => {
      profileUpdateStarted = resolve;
    });
    let activeUser: typeof user | typeof anotherUser = user;
    const logoutTokens: Array<string | null> = [];
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me") && init?.method === "PATCH") {
        profileUpdateStarted();
        return pendingUpdate.promise;
      }
      if (url.endsWith("/api/v1/me")) {
        return Promise.resolve(jsonResponse(activeUser, 200, { "X-CSRF-Token": "csrf-user-a" }));
      }
      if (url.endsWith("/api/v1/auth/logout")) {
        logoutTokens.push(new Headers(init?.headers).get("X-CSRF-Token"));
        return Promise.resolve(jsonResponse({ status: "ok" }));
      }
      if (url.endsWith("/api/v1/auth/login")) {
        activeUser = nextUser;
        return Promise.resolve(jsonResponse(nextUser, 200, { "X-CSRF-Token": nextCsrfToken }));
      }
      if (url.includes("/api/v1/repositories?")) {
        return Promise.resolve(jsonResponse({ items: [], total: 0, limit: 4, offset: 0 }));
      }
      if (url.includes("/api/v1/organizations?")) {
        return Promise.resolve(jsonResponse({ items: [], total: 0, limit: 50, offset: 0 }));
      }
      throw new Error(`Unexpected API request: ${url}`);
    });

    const userEventInstance = userEvent.setup();
    renderPage();
    expect(await screen.findByRole("heading", { name: "Profile settings" })).toBeInTheDocument();
    await userEventInstance.click(screen.getByRole("button", { name: "Save profile" }));
    await profileRequestStarted;

    await userEventInstance.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    await userEventInstance.type(screen.getByLabelText("Email address"), nextUser.email);
    await userEventInstance.type(screen.getByLabelText("Password"), "test-password");
    await userEventInstance.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText(nextUser.display_name)).toBeInTheDocument();

    await act(async () => {
      pendingUpdate.resolve(jsonResponse({ ...user, display_name: "Stale profile response" }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(apiClient.hasCsrfToken).toBe(true);
    expect(screen.getByText(nextUser.display_name)).toBeInTheDocument();

    await userEventInstance.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(logoutTokens).toEqual(["csrf-user-a", nextCsrfToken]);
  });

  it("validates required fields before making a request", async () => {
    fetchMock.mockResolvedValue(jsonResponse(user, 200, { "X-CSRF-Token": "csrf" }));
    const userEventInstance = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "Profile settings" });
    await userEventInstance.clear(screen.getByLabelText("Display name"));
    await userEventInstance.click(screen.getByRole("button", { name: "Save profile" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Display name must not be empty.");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
