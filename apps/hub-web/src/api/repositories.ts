import { ApiError, apiClient } from "./client";

export type RepositoryVisibility = "private" | "public";

export interface PersonalRepository {
  id: string;
  name: string;
  description: string | null;
  visibility: RepositoryVisibility;
  created_at: string;
  updated_at: string;
}

export interface PersonalRepositoryListResponse {
  items: PersonalRepository[];
  total: number;
  limit: number;
  offset: number;
}

export interface RepositoryListParams {
  limit?: number;
  offset?: number;
}

export interface CreatePersonalRepositoryRequest {
  name: string;
  description?: string | null;
  visibility?: RepositoryVisibility;
}

export interface UpdatePersonalRepositoryRequest {
  name?: string;
  description?: string | null;
  visibility?: RepositoryVisibility;
}

export interface RepositoryReadOptions {
  signal?: AbortSignal;
}

export function normalizeRepositoryListParams({
  limit = 50,
  offset = 0,
}: RepositoryListParams = {}): Required<RepositoryListParams> {
  return { limit, offset };
}

function requireResponse<T>(response: T | undefined): T {
  if (response !== undefined) return response;
  throw new ApiError("The Hub API returned an empty repository response.", {
    status: 200,
    code: "invalid_response",
    requestId: null,
  });
}

function repositoryPath(repositoryId: string): string {
  return `/repositories/${encodeURIComponent(repositoryId)}`;
}

export async function listPersonalRepositories(
  params: RepositoryListParams = {},
  options: RepositoryReadOptions = {},
): Promise<PersonalRepositoryListResponse> {
  const { limit, offset } = normalizeRepositoryListParams(params);
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return requireResponse(
    await apiClient.get<PersonalRepositoryListResponse>(`/repositories?${query}`, options),
  );
}

export async function createPersonalRepository(
  request: CreatePersonalRepositoryRequest,
): Promise<PersonalRepository> {
  const body: CreatePersonalRepositoryRequest = {
    ...request,
    visibility: request.visibility ?? "private",
  };
  return requireResponse(
    await apiClient.post<PersonalRepository, CreatePersonalRepositoryRequest>(
      "/repositories",
      body,
    ),
  );
}

export async function getPersonalRepository(
  repositoryId: string,
  options: RepositoryReadOptions = {},
): Promise<PersonalRepository> {
  return requireResponse(
    await apiClient.get<PersonalRepository>(repositoryPath(repositoryId), options),
  );
}

export async function updatePersonalRepository(
  repositoryId: string,
  changes: UpdatePersonalRepositoryRequest,
): Promise<PersonalRepository> {
  const body: UpdatePersonalRepositoryRequest = {};
  if (changes.name !== undefined) body.name = changes.name;
  if (changes.description !== undefined) body.description = changes.description;
  if (changes.visibility !== undefined) body.visibility = changes.visibility;

  return requireResponse(
    await apiClient.patch<PersonalRepository, UpdatePersonalRepositoryRequest>(
      repositoryPath(repositoryId),
      body,
    ),
  );
}

export async function deletePersonalRepository(repositoryId: string): Promise<void> {
  await apiClient.delete<void>(repositoryPath(repositoryId));
}
