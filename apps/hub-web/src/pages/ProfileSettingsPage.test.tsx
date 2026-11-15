import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
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
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/me") && init?.method === "PATCH") {
        updateBody = JSON.parse(String(init.body));
        return jsonResponse(updated);
      }
      if (url.endsWith("/api/v1/me")) return jsonResponse(user, 200, { "X-CSRF-Token": "csrf" });
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
