import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiClient } from "./client";
import {
  createPersonalRepository,
  deletePersonalRepository,
  getPersonalRepository,
  listPersonalRepositories,
  updatePersonalRepository,
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
