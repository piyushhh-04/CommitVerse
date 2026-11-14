import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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
    fetchMock.mockResolvedValueOnce(
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
