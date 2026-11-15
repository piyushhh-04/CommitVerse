import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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
});
