import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiClient } from "./client";
import {
  createPersonalRepository,
  createRepositoryInvitation,
  deletePersonalRepository,
  getPersonalRepository,
  grantRepositoryPermission,
  listRepositoryInvitations,
  listPersonalRepositories,
  listRepositoryPermissions,
  acceptRepositoryInvitation,
  revokeRepositoryInvitation,
  revokeRepositoryPermission,
  updatePersonalRepository,
  updateRepositoryPermission,
  type PersonalRepository,
} from "./repositories";

const fetchMock = vi.fn<typeof fetch>();
const repository: PersonalRepository = {
  id: "6f577861-febc-4c87-8949-e9201471141f",
  name: "sample-repository",
  description: "A personal repository",
  visibility: "private",
  created_at: "2026-11-15T10:00:00Z",
  updated_at: "2026-11-15T10:00:00Z",
};

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

describe("personal repository API", () => {
  it("uses the backend pagination defaults and forwards read cancellation", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ items: [repository], total: 1, limit: 50, offset: 0 }),
    );
    const controller = new AbortController();

    await expect(listPersonalRepositories({}, { signal: controller.signal })).resolves.toEqual({
      items: [repository],
      total: 1,
      limit: 50,
      offset: 0,
    });

    const [url, options] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe("/api/v1/repositories?limit=50&offset=0");
    expect(options?.method).toBe("GET");
    expect(options?.signal).toBe(controller.signal);
  });

  it("serializes explicit list pagination parameters", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ items: [], total: 53, limit: 20, offset: 40 }));

    await listPersonalRepositories({ limit: 20, offset: 40 });

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/repositories?limit=20&offset=40");
  });

  it("creates with supported fields and defaults visibility to private", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(repository, 201));

    await createPersonalRepository({ name: "sample-repository", description: null });

    const [url, options] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe("/api/v1/repositories");
    expect(options?.method).toBe("POST");
    expect(JSON.parse(String(options?.body))).toEqual({
      name: "sample-repository",
      description: null,
      visibility: "private",
    });
  });

  it("gets details by ID and forwards read cancellation", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(repository));
    const controller = new AbortController();

    await expect(
      getPersonalRepository(repository.id, { signal: controller.signal }),
    ).resolves.toEqual(repository);

    const [url, options] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe(`/api/v1/repositories/${repository.id}`);
    expect(options?.method).toBe("GET");
    expect(options?.signal).toBe(controller.signal);
  });

  it("updates only supported fields while preserving an explicit null description", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ ...repository, description: null }));
    const changes = {
      description: null,
      owner_user_id: "not-an-accepted-field",
    };

    await updatePersonalRepository(repository.id, changes);

    const [url, options] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe(`/api/v1/repositories/${repository.id}`);
    expect(options?.method).toBe("PATCH");
    expect(JSON.parse(String(options?.body))).toEqual({ description: null });
  });

  it("deletes with an empty 204 response", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));

    await expect(deletePersonalRepository(repository.id)).resolves.toBeUndefined();

    const [url, options] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe(`/api/v1/repositories/${repository.id}`);
    expect(options?.method).toBe("DELETE");
    expect(options?.body).toBeUndefined();
  });

  it("supports direct repository permission list, grant, role update, and revoke", async () => {
    const permission = {
      user_id: "user-2",
      role: "reader",
      created_at: "2026-11-15T10:00:00Z",
      updated_at: "2026-11-15T10:00:00Z",
    };
    fetchMock
      .mockResolvedValueOnce(jsonResponse([permission]))
      .mockResolvedValueOnce(jsonResponse(permission, 201))
      .mockResolvedValueOnce(jsonResponse({ ...permission, role: "writer" }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    await expect(listRepositoryPermissions(repository.id)).resolves.toEqual([permission]);
    await grantRepositoryPermission(repository.id, "user-2", "reader");
    await updateRepositoryPermission(repository.id, "user-2", "writer");
    await revokeRepositoryPermission(repository.id, "user-2");

    expect(fetchMock.mock.calls.map(([url, options]) => [url, options?.method])).toEqual([
      [`/api/v1/repositories/${repository.id}/permissions`, "GET"],
      [`/api/v1/repositories/${repository.id}/permissions`, "POST"],
      [`/api/v1/repositories/${repository.id}/permissions/user-2`, "PATCH"],
      [`/api/v1/repositories/${repository.id}/permissions/user-2`, "DELETE"],
    ]);
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({
      user_id: "user-2",
      role: "reader",
    });
    expect(JSON.parse(String(fetchMock.mock.calls[2]?.[1]?.body))).toEqual({ role: "writer" });
  });

  it("supports repository invitation creation, listing, revocation, and acceptance", async () => {
    const invitation = {
      id: "invitation-1",
      target_email: "reader@example.test",
      role: "reader",
      status: "pending",
      expires_at: "2026-11-22T10:00:00Z",
      created_at: "2026-11-15T10:00:00Z",
    };
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ ...invitation, token: "secret-invitation-token" }, 201))
      .mockResolvedValueOnce(jsonResponse({ items: [invitation], total: 1, limit: 100, offset: 0 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(jsonResponse({ repository_id: repository.id, role: "reader" }));

    await expect(
      createRepositoryInvitation(repository.id, "reader@example.test", "reader", 7),
    ).resolves.toMatchObject({ ...invitation, token: "secret-invitation-token" });
    await expect(listRepositoryInvitations(repository.id)).resolves.toMatchObject({
      items: [invitation],
      total: 1,
    });
    await revokeRepositoryInvitation(repository.id, "invitation-1");
    await expect(acceptRepositoryInvitation("secret-invitation-token")).resolves.toEqual({
      repository_id: repository.id,
      role: "reader",
    });

    expect(fetchMock.mock.calls.map(([url, options]) => [url, options?.method])).toEqual([
      [`/api/v1/repositories/${repository.id}/invitations`, "POST"],
      [`/api/v1/repositories/${repository.id}/invitations?limit=100&offset=0`, "GET"],
      [`/api/v1/repositories/${repository.id}/invitations/invitation-1`, "DELETE"],
      ["/api/v1/repositories/invitations/secret-invitation-token/accept", "POST"],
    ]);
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      target_email: "reader@example.test",
      role: "reader",
      expires_in_days: 7,
    });
  });

  it("preserves API errors, request IDs, and validation details", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          error: {
            code: "validation_error",
            message: "Request validation failed.",
            details: [
              { field: "name", code: "string_pattern_mismatch", message: "Invalid value." },
            ],
          },
          request_id: "repository-request-1",
        },
        422,
      ),
    );

    await expect(createPersonalRepository({ name: "../invalid" })).rejects.toMatchObject({
      name: "ApiError",
      status: 422,
      code: "validation_error",
      requestId: "repository-request-1",
      details: [{ field: "name", code: "string_pattern_mismatch", message: "Invalid value." }],
    } satisfies Partial<ApiError>);
  });
});
