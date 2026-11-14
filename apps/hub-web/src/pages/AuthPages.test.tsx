import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";
import { apiClient } from "../api/client";
import { AppRoutes } from "../app/AppRoutes";
import { ThemeProvider } from "../theme/ThemeProvider";
import type { AuthUser } from "../auth/types";

const user: AuthUser = {
  id: "user-1",
  email: "dev@example.test",
  username: "dev",
  display_name: "Developer",
};
const fetchMock = vi.fn<typeof fetch>();

function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="current-location">
      {location.pathname}
      {location.search}
      {location.hash}
    </output>
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function renderAtPath(path: string, state?: unknown) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[{ pathname: path, state }]}>
          <LocationProbe />
          <AppRoutes />
        </MemoryRouter>
      </QueryClientProvider>
    </ThemeProvider>,
  );
}

function unauthorizedResponse() {
  return new Response(
    JSON.stringify({
      error: { code: "authentication_required", message: "Authentication required." },
      request_id: "req-anonymous",
    }),
    { status: 401, headers: { "Content-Type": "application/json" } },
  );
}

function userResponse(csrfToken = "csrf-session") {
  return new Response(JSON.stringify(user), {
    status: 200,
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
  });
}

function errorResponse(
  status: number,
  code: string,
  message: string,
  details?: Array<{ field: string; code: string; message: string }>,
) {
  return new Response(
    JSON.stringify({ error: { code, message, details }, request_id: "req-error" }),
    {
      status,
      headers: { "Content-Type": "application/json" },
    },
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

describe("authentication pages", () => {
  it("validates login fields before sending credentials", async () => {
    fetchMock.mockResolvedValueOnce(unauthorizedResponse());
    const userEventInstance = userEvent.setup();
    renderAtPath("/login");

    await screen.findByRole("heading", { name: "Sign in" });
    await userEventInstance.type(screen.getByLabelText("Email address"), "not-an-email");
    await userEventInstance.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
    expect(screen.getByText("Enter your password.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Email address")).toHaveAttribute("aria-invalid", "true");
  });

  it("logs in and returns to the intended protected destination", async () => {
    let loginBody: unknown;
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) return unauthorizedResponse();
      if (url.endsWith("/api/v1/auth/login")) {
        loginBody = JSON.parse(String(init?.body));
        return userResponse("csrf-after-login");
      }
      throw new Error(`Unexpected API request: ${url}`);
    });
    const userEventInstance = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <ThemeProvider>
        <QueryClientProvider client={queryClient}>
          <MemoryRouter
            initialEntries={[
              {
                pathname: "/login",
                state: { from: { pathname: "/app/repositories", search: "?scope=personal" } },
              },
            ]}
          >
            <LocationProbe />
            <AppRoutes />
          </MemoryRouter>
        </QueryClientProvider>
      </ThemeProvider>,
    );

    await userEventInstance.type(screen.getByLabelText("Email address"), " dev@example.test ");
    await userEventInstance.type(screen.getByLabelText("Password"), "test-password");
    await userEventInstance.click(screen.getByRole("button", { name: "Sign in" }));

    expect(
      await screen.findByRole("heading", { name: "Repositories", level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("current-location")).toHaveTextContent(
      "/app/repositories?scope=personal",
    );
    expect(screen.getByRole("link", { name: "Repositories" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(loginBody).toEqual({ email: "dev@example.test", password: "test-password" });
    expect(apiClient.hasCsrfToken).toBe(true);
    expect(queryClient.getMutationCache().getAll()).toHaveLength(0);
    expect(window.localStorage.getItem("commitverse-theme")).not.toContain("test-password");
    expect(window.sessionStorage.length).toBe(0);
  });

  it.each(["https://evil.example", "//evil.example", "/\\\\evil.example"])(
    "rejects hostile return destination %s and uses the safe default",
    async (pathname) => {
      fetchMock.mockImplementation(async (input) => {
        const url = String(input);
        if (url.endsWith("/api/v1/me")) return unauthorizedResponse();
        if (url.endsWith("/api/v1/auth/login")) return userResponse("csrf-after-login");
        throw new Error(`Unexpected API request: ${url}`);
      });
      const userEventInstance = userEvent.setup();
      renderAtPath("/login", { from: { pathname } });

      await userEventInstance.type(screen.getByLabelText("Email address"), "dev@example.test");
      await userEventInstance.type(screen.getByLabelText("Password"), "test-password");
      await userEventInstance.click(screen.getByRole("button", { name: "Sign in" }));

      expect(await screen.findByRole("heading", { name: "Your workspace" })).toBeInTheDocument();
      expect(screen.getByTestId("current-location")).toHaveTextContent("/app");
      expect(screen.getByTestId("current-location")).not.toHaveTextContent("evil.example");
    },
  );

  it("shows a backend login error without clearing the form", async () => {
    fetchMock.mockImplementation(async (input) => {
      if (String(input).endsWith("/api/v1/me")) return unauthorizedResponse();
      if (String(input).endsWith("/api/v1/auth/login")) {
        return errorResponse(401, "authentication_failed", "Invalid email or password.");
      }
      throw new Error(`Unexpected API request: ${String(input)}`);
    });
    const userEventInstance = userEvent.setup();
    renderAtPath("/login");

    await userEventInstance.type(screen.getByLabelText("Email address"), "dev@example.test");
    await userEventInstance.type(screen.getByLabelText("Password"), "incorrect-password");
    await userEventInstance.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password.");
    expect(screen.getByLabelText("Password")).toHaveValue("incorrect-password");
  });

  it("announces the login loading state and supports password visibility", async () => {
    const pendingLogin = deferred<Response>();
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) return Promise.resolve(unauthorizedResponse());
      if (url.endsWith("/api/v1/auth/login")) return pendingLogin.promise;
      throw new Error(`Unexpected API request: ${url}`);
    });
    const userEventInstance = userEvent.setup();
    renderAtPath("/login");

    await userEventInstance.type(screen.getByLabelText("Email address"), "dev@example.test");
    const passwordInput = screen.getByLabelText("Password");
    await userEventInstance.type(passwordInput, "test-password");
    await userEventInstance.click(screen.getByRole("button", { name: "Show password" }));
    expect(passwordInput).toHaveAttribute("type", "text");
    await userEventInstance.click(screen.getByRole("button", { name: "Hide password" }));
    expect(passwordInput).toHaveAttribute("type", "password");
    await userEventInstance.click(screen.getByRole("button", { name: "Sign in" }));

    const pendingButton = await screen.findByRole("button", { name: "Signing in..." });
    expect(pendingButton).toBeDisabled();
    expect(screen.getByRole("form", { name: "Sign in" })).toHaveAttribute("aria-busy", "true");

    pendingLogin.resolve(userResponse("csrf-after-login"));
    expect(await screen.findByRole("heading", { name: "Your workspace" })).toBeInTheDocument();
  });

  it("validates registration fields using the backend contract", async () => {
    fetchMock.mockResolvedValueOnce(unauthorizedResponse());
    const userEventInstance = userEvent.setup();
    renderAtPath("/register");

    await userEventInstance.click(screen.getByRole("button", { name: "Create your account" }));

    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
    expect(screen.getByText("Enter a username.")).toBeInTheDocument();
    expect(screen.getByText("Enter your password.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("registers with supported fields and establishes the authenticated session", async () => {
    let registrationBody: unknown;
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) return unauthorizedResponse();
      if (url.endsWith("/api/v1/auth/register")) {
        registrationBody = JSON.parse(String(init?.body));
        return userResponse("csrf-after-register");
      }
      throw new Error(`Unexpected API request: ${url}`);
    });
    const userEventInstance = userEvent.setup();
    renderAtPath("/register");

    await userEventInstance.type(screen.getByLabelText("Email address"), "dev@example.test");
    await userEventInstance.type(screen.getByLabelText("Username"), "dev");
    await userEventInstance.type(screen.getByLabelText("Display name (optional)"), "Developer");
    await userEventInstance.type(screen.getByLabelText("Password"), "test-password");
    await userEventInstance.click(screen.getByRole("button", { name: "Create your account" }));

    expect(await screen.findByText("Developer")).toBeInTheDocument();
    expect(registrationBody).toEqual({
      email: "dev@example.test",
      password: "test-password",
      username: "dev",
      display_name: "Developer",
    });
    expect(apiClient.hasCsrfToken).toBe(true);
  });

  it("shows registration conflicts from the API", async () => {
    fetchMock.mockImplementation(async (input) => {
      if (String(input).endsWith("/api/v1/me")) return unauthorizedResponse();
      if (String(input).endsWith("/api/v1/auth/register")) {
        return errorResponse(409, "account_exists", "An account with this email already exists.");
      }
      throw new Error(`Unexpected API request: ${String(input)}`);
    });
    const userEventInstance = userEvent.setup();
    renderAtPath("/register");

    await userEventInstance.type(screen.getByLabelText("Email address"), "dev@example.test");
    await userEventInstance.type(screen.getByLabelText("Username"), "dev");
    await userEventInstance.type(screen.getByLabelText("Password"), "test-password");
    await userEventInstance.click(screen.getByRole("button", { name: "Create your account" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "An account with this email already exists.",
    );
  });

  it("renders authenticated identity, accessible mobile navigation, theme control, and logout", async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me")) return userResponse();
      if (url.endsWith("/api/v1/auth/logout")) {
        expect(new Headers(init?.headers).get("X-CSRF-Token")).toBe("csrf-session");
        return new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`Unexpected API request: ${url}`);
    });
    const userEventInstance = userEvent.setup();
    renderAtPath("/app");

    expect(await screen.findByText("Developer")).toBeInTheDocument();
    expect(screen.getByText("dev@example.test")).toBeInTheDocument();
    const navigation = screen.getByRole("navigation", { name: "Application navigation" });
    expect(within(navigation).getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(within(navigation).getByRole("link", { name: "Repositories" })).toBeInTheDocument();
    expect(within(navigation).getByRole("link", { name: "Organizations" })).toBeInTheDocument();

    const menuButton = screen.getByRole("button", { name: "Open application navigation" });
    await userEventInstance.click(menuButton);
    expect(menuButton).toHaveAttribute("aria-expanded", "true");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByRole("button", { name: "Open application navigation" })).toHaveFocus();

    await userEventInstance.click(screen.getByRole("button", { name: "Switch to dark theme" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");

    await userEventInstance.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    await waitFor(() => expect(apiClient.hasCsrfToken).toBe(false));
  });
});
