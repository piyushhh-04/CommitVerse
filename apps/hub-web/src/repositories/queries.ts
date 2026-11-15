import { mutationOptions, queryOptions, QueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/client";
import {
  createPersonalRepository,
  deletePersonalRepository,
  getPersonalRepository,
  listPersonalRepositories,
  normalizeRepositoryListParams,
  updatePersonalRepository,
  type CreatePersonalRepositoryRequest,
  type PersonalRepository,
  type RepositoryListParams,
  type UpdatePersonalRepositoryRequest,
} from "../api/repositories";

export const personalRepositoryQueryKeys = {
  all: ["repositories"] as const,
  forUser: (userId: string) => ["repositories", userId] as const,
  lists: (userId: string) => ["repositories", userId, "list"] as const,
  list: (userId: string, params: RepositoryListParams = {}) =>
    ["repositories", userId, "list", normalizeRepositoryListParams(params)] as const,
  details: (userId: string) => ["repositories", userId, "detail"] as const,
  detail: (userId: string, repositoryId: string) =>
    ["repositories", userId, "detail", repositoryId] as const,
};

export const personalRepositoryMutationKeys = {
  forUser: (userId: string) => ["repositories", userId, "mutation"] as const,
  create: (userId: string) => ["repositories", userId, "mutation", "create"] as const,
  update: (userId: string) => ["repositories", userId, "mutation", "update"] as const,
  delete: (userId: string) => ["repositories", userId, "mutation", "delete"] as const,
};

const repositoryMutationClients = new WeakMap<QueryClient, QueryClient>();
const activeRepositoryUsers = new WeakMap<QueryClient, string | null>();

export function personalRepositoryMutationClient(queryClient: QueryClient): QueryClient {
  let mutationClient = repositoryMutationClients.get(queryClient);
  if (!mutationClient) {
    mutationClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    repositoryMutationClients.set(queryClient, mutationClient);
  }
  return mutationClient;
}

export function setPersonalRepositoryIdentity(
  queryClient: QueryClient,
  userId: string | null,
): void {
  activeRepositoryUsers.set(queryClient, userId);
}

export async function clearPersonalRepositoryState(
  queryClient: QueryClient,
  nextUserId: string | null,
): Promise<void> {
  setPersonalRepositoryIdentity(queryClient, nextUserId);
  repositoryMutationClients.get(queryClient)?.getMutationCache().clear();
  await queryClient.cancelQueries({ queryKey: personalRepositoryQueryKeys.all });
  queryClient.removeQueries({ queryKey: personalRepositoryQueryKeys.all });
}

function isActiveRepositoryUser(queryClient: QueryClient, userId: string): boolean {
  if (!activeRepositoryUsers.has(queryClient)) {
    activeRepositoryUsers.set(queryClient, userId);
  }
  return activeRepositoryUsers.get(queryClient) === userId;
}

export function personalRepositoryListQueryOptions(
  userId: string,
  params: RepositoryListParams = {},
) {
  const normalizedParams = normalizeRepositoryListParams(params);
  return queryOptions({
    queryKey: personalRepositoryQueryKeys.list(userId, normalizedParams),
    queryFn: ({ signal }) => listPersonalRepositories(normalizedParams, { signal }),
  });
}

export function personalRepositoryDetailQueryOptions(userId: string, repositoryId: string) {
  return queryOptions({
    queryKey: personalRepositoryQueryKeys.detail(userId, repositoryId),
    queryFn: ({ signal }) => getPersonalRepository(repositoryId, { signal }),
  });
}

export function personalRepositoryMutationOptions(queryClient: QueryClient, userId: string) {
  if (!activeRepositoryUsers.has(queryClient)) {
    activeRepositoryUsers.set(queryClient, userId);
  }

  return {
    create: mutationOptions<PersonalRepository, ApiError, CreatePersonalRepositoryRequest>({
      mutationKey: personalRepositoryMutationKeys.create(userId),
      gcTime: 0,
      retry: false,
      mutationFn: (request: CreatePersonalRepositoryRequest) => createPersonalRepository(request),
      onSuccess: async () => {
        if (!isActiveRepositoryUser(queryClient, userId)) return;
        await queryClient.invalidateQueries({
          queryKey: personalRepositoryQueryKeys.lists(userId),
        });
      },
    }),
    update: mutationOptions<
      PersonalRepository,
      ApiError,
      { repositoryId: string; changes: UpdatePersonalRepositoryRequest }
    >({
      mutationKey: personalRepositoryMutationKeys.update(userId),
      gcTime: 0,
      retry: false,
      mutationFn: (variables: { repositoryId: string; changes: UpdatePersonalRepositoryRequest }) =>
        updatePersonalRepository(variables.repositoryId, variables.changes),
      onSuccess: async (_repository, variables) => {
        if (!isActiveRepositoryUser(queryClient, userId)) return;
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: personalRepositoryQueryKeys.detail(userId, variables.repositoryId),
            exact: true,
          }),
          queryClient.invalidateQueries({
            queryKey: personalRepositoryQueryKeys.lists(userId),
          }),
        ]);
      },
    }),
    delete: mutationOptions<void, ApiError, string>({
      mutationKey: personalRepositoryMutationKeys.delete(userId),
      gcTime: 0,
      retry: false,
      mutationFn: (repositoryId: string) => deletePersonalRepository(repositoryId),
      onSuccess: async (_result, repositoryId) => {
        if (!isActiveRepositoryUser(queryClient, userId)) return;
        const detailKey = personalRepositoryQueryKeys.detail(userId, repositoryId);
        await queryClient.cancelQueries({ queryKey: detailKey, exact: true });
        queryClient.removeQueries({ queryKey: detailKey, exact: true });
        await queryClient.invalidateQueries({
          queryKey: personalRepositoryQueryKeys.lists(userId),
        });
      },
    }),
  };
}
