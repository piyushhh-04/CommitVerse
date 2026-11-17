import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "../api/client";
import { transitionProtectedQueryIdentity } from "../app/protectedQueryCache";
import { RepositoryAccessPanel } from "./RepositoryAccessPanel";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
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

describe("RepositoryAccessPanel", () => {
  it("searches for direct collaborators and manages one-time repository invitations", async () => {
    const repositoryId = "repository-1";
    const ownerId = "owner-1";
    const permission = {
      user_id: "reader-1",
      role: "reader",
      created_at: "2026-11-15T10:00:00Z",
      updated_at: "2026-11-15T10:00:00Z",
    };
    const invitation = {
      id: "invitation-1",
      target_email: "reader@example.test",
      role: "reader",
      status: "pending",
      expires_at: "2026-11-22T10:00:00Z",
      created_at: "2026-11-15T10:00:00Z",
    };
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith(`/repositories/${repositoryId}/permissions`) && init?.method === "POST") {
        return jsonResponse(permission, 201);
      }
      if (url.endsWith(`/repositories/${repositoryId}/permissions`)) {
        return jsonResponse([permission]);
      }
      if (url.includes("/users/search?")) {
        return jsonResponse({
          items: [{ id: "reader-1", username: "reader", display_name: "Repository Reader" }],
          query: "reader",
          limit: 20,
        });
      }
      if (url.endsWith(`/repositories/${repositoryId}/invitations`) && init?.method === "POST") {
        return jsonResponse({ ...invitation, token: "one-time-token" }, 201);
      }
      if (url.includes(`/repositories/${repositoryId}/invitations?`)) {
        return jsonResponse({ items: [invitation], total: 1, limit: 100, offset: 0 });
      }
      throw new Error(`Unexpected API request: ${url}`);
    });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    await transitionProtectedQueryIdentity(queryClient, ownerId);
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={queryClient}>
        <RepositoryAccessPanel repositoryId={repositoryId} userId={ownerId} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Account reader-1")).toBeInTheDocument();
    await user.type(
      screen.getByRole("textbox", { name: "Search users to grant repository access" }),
      "reader",
    );
    await user.click(await screen.findByRole("button", { name: "Repository Reader (@reader)" }));
    await user.click(screen.getByRole("button", { name: "Grant access" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        `/api/v1/repositories/${repositoryId}/permissions`,
        expect.objectContaining({ method: "POST" }),
      ),
    );

    await user.type(
      screen.getByRole("textbox", { name: "Invitation email" }),
      "reader@example.test",
    );
    await user.click(screen.getByRole("button", { name: "Create invitation" }));

    expect(await screen.findByText("one-time-token")).toBeInTheDocument();
    expect(
      screen.getByText(/Share this one-time token with reader@example\.test/),
    ).toBeInTheDocument();
    expect(
      screen.getByText("reader@example.test", { selector: ".repository-name-link" }),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/repositories/${repositoryId}/invitations`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          target_email: "reader@example.test",
          role: "reader",
          expires_in_days: 7,
        }),
      }),
    );
  });
});
