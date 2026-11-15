import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "./client";
import {
  acceptOrganizationInvitation,
  createOrganizationInvitation,
  listOrganizationInvitations,
  listOrganizationMembers,
  listOrganizations,
  revokeOrganizationInvitation,
  transferOrganizationOwnership,
} from "./organizations";

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  apiClient.setCsrfToken("csrf-test");
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  apiClient.setCsrfToken(null);
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

describe("organization API functions", () => {
  it("lists organizations through the bounded member endpoint", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ items: [], total: 0, limit: 50, offset: 0 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(listOrganizations()).resolves.toMatchObject({ items: [], total: 0 });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/organizations?limit=50&offset=0",
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("keeps membership and ownership mutations on the protected API contract", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ items: [], total: 0, limit: 100, offset: 0 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "ok" }), { status: 200 }));

    await listOrganizationMembers("org/1");
    await transferOrganizationOwnership("org/1", "user/2", "password");

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/v1/organizations/org%2F1/members?limit=100&offset=0",
    );
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/v1/organizations/org%2F1/transfer-ownership");
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ target_user_id: "user/2", current_password: "password" }),
      }),
    );
  });

  it("supports scoped invitation issue, listing, revocation, and acceptance", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "invite-1",
            target_email: "member@example.test",
            role: "member",
            status: "pending",
            expires_at: "2026-11-22T00:00:00Z",
            created_at: "2026-11-15T00:00:00Z",
            token: "t".repeat(43),
          }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ items: [], total: 0, limit: 100, offset: 0 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ organization_id: "org-1", role: "member" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

    await createOrganizationInvitation("org/1", "member@example.test", "member");
    await listOrganizationInvitations("org/1");
    await revokeOrganizationInvitation("org/1", "invite/1");
    await acceptOrganizationInvitation("t".repeat(43));

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/organizations/org%2F1/invitations");
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      "/api/v1/organizations/org%2F1/invitations?limit=100&offset=0",
    );
    expect(fetchMock.mock.calls[2]?.[0]).toBe(
      "/api/v1/organizations/org%2F1/invitations/invite%2F1",
    );
    expect(fetchMock.mock.calls[3]?.[0]).toContain("/api/v1/invitations/");
  });
});
