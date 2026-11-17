import { mutationOptions, queryOptions, QueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/client";
import { protectedQueryKey, protectedQueryKeys } from "../app/protectedQueryCache";
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
  all: protectedQueryKeys.all,
  forUser: (userId: string) => protectedQueryKey(userId, "repositories"),
  lists: (userId: string) => protectedQueryKey(userId, "repositories", "list"),
  list: (userId: string, params: RepositoryListParams = {}) =>
    protectedQueryKey(userId, "repositories", "list", normalizeRepositoryListParams(params)),
  details: (userId: string) => protectedQueryKey(userId, "repositories", "detail"),
  detail: (userId: string, repositoryId: string) =>
    protectedQueryKey(userId, "repositories", "detail", repositoryId),
};

export const personalRepositoryMutationKeys = {
  forUser: (userId: string) => protectedQueryKey(userId, "repositories", "mutation"),
  create: (userId: string) => protectedQueryKey(userId, "repositories", "mutation", "create"),
  update: (userId: string) => protectedQueryKey(userId, "repositories", "mutation", "update"),
  delete: (userId: string) => protectedQueryKey(userId, "repositories", "mutation", "delete"),
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

export function clearPersonalRepositoryMutationState(
  queryClient: QueryClient,
  nextUserId: string | null,
): void {
  setPersonalRepositoryIdentity(queryClient, nextUserId);
  repositoryMutationClients.get(queryClient)?.getMutationCache().clear();
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
