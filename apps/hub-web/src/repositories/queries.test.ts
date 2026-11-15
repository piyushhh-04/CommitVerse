import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "../api/client";
import type { PersonalRepository, PersonalRepositoryListResponse } from "../api/repositories";
import {
  clearPersonalRepositoryState,
  personalRepositoryDetailQueryOptions,
  personalRepositoryListQueryOptions,
  personalRepositoryMutationClient,
  personalRepositoryMutationOptions,
  personalRepositoryQueryKeys,
} from "./queries";

const fetchMock = vi.fn<typeof fetch>();
const repository: PersonalRepository = {
  id: "6f577861-febc-4c87-8949-e9201471141f",
  name: "sample-repository",
  description: null,
  visibility: "private",
  created_at: "2026-11-15T10:00:00Z",
  updated_at: "2026-11-15T10:00:00Z",
};
const emptyList: PersonalRepositoryListResponse = {
  items: [],
  total: 0,
  limit: 50,
  offset: 0,
};
const queryClients: QueryClient[] = [];
const mutationClients: QueryClient[] = [];

function createQueryClient(): QueryClient {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  queryClients.push(queryClient);
  return queryClient;
}

function getRepositoryMutationCache(queryClient: QueryClient) {
  const mutationClient = personalRepositoryMutationClient(queryClient);
  mutationClients.push(mutationClient);
  return mutationClient.getMutationCache();
}

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
  for (const queryClient of queryClients.splice(0)) queryClient.clear();
  for (const mutationClient of mutationClients.splice(0)) mutationClient.clear();
});

describe("personal repository queries", () => {
  it("uses stable keys with user and normalized pagination scope", () => {
    expect(personalRepositoryQueryKeys.list("user-1")).toEqual([
      "repositories",
      "user-1",
      "list",
      { limit: 50, offset: 0 },
    ]);
    expect(personalRepositoryQueryKeys.list("user-1", { offset: 10, limit: 20 })).toEqual(
      personalRepositoryQueryKeys.list("user-1", { limit: 20, offset: 10 }),
    );
    expect(personalRepositoryQueryKeys.list("user-1")).not.toEqual(
      personalRepositoryQueryKeys.list("user-2"),
    );
    expect(personalRepositoryQueryKeys.detail("user-1", repository.id)).not.toEqual(
      personalRepositoryQueryKeys.detail("user-2", repository.id),
    );
  });

  it("fetches list and detail query options with normalized defaults and cancellation signals", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(emptyList))
      .mockResolvedValueOnce(jsonResponse(repository));
    const queryClient = createQueryClient();
    const listOptions = personalRepositoryListQueryOptions("user-1");
    const detailOptions = personalRepositoryDetailQueryOptions("user-1", repository.id);

    await expect(queryClient.fetchQuery(listOptions)).resolves.toEqual(emptyList);
    await expect(queryClient.fetchQuery(detailOptions)).resolves.toEqual(repository);

    expect(listOptions.queryKey).toEqual(personalRepositoryQueryKeys.list("user-1"));
    expect(detailOptions.queryKey).toEqual(
      personalRepositoryQueryKeys.detail("user-1", repository.id),
    );
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/repositories?limit=50&offset=0");
    expect(fetchMock.mock.calls[1]?.[0]).toBe(`/api/v1/repositories/${repository.id}`);
    expect(fetchMock.mock.calls[0]?.[1]?.signal).toBeInstanceOf(AbortSignal);
    expect(fetchMock.mock.calls[1]?.[1]?.signal).toBeInstanceOf(AbortSignal);
  });

  it("invalidates user-scoped lists after creation", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(repository, 201));
    const queryClient = createQueryClient();
    const listKey = personalRepositoryQueryKeys.list("user-1");
    queryClient.setQueryData(listKey, emptyList);
    const mutationCache = getRepositoryMutationCache(queryClient);
    const mutation = mutationCache.build(
      personalRepositoryMutationClient(queryClient),
      personalRepositoryMutationOptions(queryClient, "user-1").create,
    );

    await mutation.execute({ name: repository.name });

    expect(queryClient.getQueryState(listKey)?.isInvalidated).toBe(true);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/repositories");
  });

  it("invalidates the updated detail and lists", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ ...repository, visibility: "public" }));
    const queryClient = createQueryClient();
    const listKey = personalRepositoryQueryKeys.list("user-1");
    const detailKey = personalRepositoryQueryKeys.detail("user-1", repository.id);
    queryClient.setQueryData(listKey, emptyList);
    queryClient.setQueryData(detailKey, repository);
    const mutationCache = getRepositoryMutationCache(queryClient);
    const mutation = mutationCache.build(
      personalRepositoryMutationClient(queryClient),
      personalRepositoryMutationOptions(queryClient, "user-1").update,
    );

    await mutation.execute({
      repositoryId: repository.id,
      changes: { visibility: "public" },
    });

    expect(queryClient.getQueryState(detailKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(listKey)?.isInvalidated).toBe(true);
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      visibility: "public",
    });
  });

  it("removes the deleted detail and invalidates lists", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    const queryClient = createQueryClient();
    const listKey = personalRepositoryQueryKeys.list("user-1");
    const detailKey = personalRepositoryQueryKeys.detail("user-1", repository.id);
    queryClient.setQueryData(listKey, emptyList);
    queryClient.setQueryData(detailKey, repository);
    const mutationCache = getRepositoryMutationCache(queryClient);
    const mutation = mutationCache.build(
      personalRepositoryMutationClient(queryClient),
      personalRepositoryMutationOptions(queryClient, "user-1").delete,
    );

    await mutation.execute(repository.id);

    expect(queryClient.getQueryState(detailKey)).toBeUndefined();
    expect(queryClient.getQueryState(listKey)?.isInvalidated).toBe(true);
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe("DELETE");
  });

  it("isolates repository mutations and guards an in-flight result after an account switch", async () => {
    let resolveResponse!: (response: Response) => void;
    fetchMock.mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          resolveResponse = resolve;
        }),
    );
    const queryClient = createQueryClient();
    const mutationClient = personalRepositoryMutationClient(queryClient);
    mutationClients.push(mutationClient);
    const listKeyForNextUser = personalRepositoryQueryKeys.list("user-2");
    const unrelatedMutation = queryClient.getMutationCache().build(queryClient, {
      mutationFn: async () => "unrelated",
    });
    const mutation = mutationClient
      .getMutationCache()
      .build(mutationClient, personalRepositoryMutationOptions(queryClient, "user-1").create);
    const mutationPromise = mutation.execute({ name: repository.name });
    await vi.waitFor(() => expect(resolveResponse).toBeTypeOf("function"));

    await clearPersonalRepositoryState(queryClient, "user-2");
    queryClient.setQueryData(listKeyForNextUser, emptyList);
    resolveResponse(jsonResponse(repository, 201));
    await expect(mutationPromise).resolves.toEqual(repository);

    expect(mutationClient.getMutationCache().getAll()).toHaveLength(0);
    expect(queryClient.getMutationCache().getAll()).toContain(unrelatedMutation);
    expect(queryClient.getQueryState(listKeyForNextUser)?.isInvalidated).toBe(false);
  });
});
