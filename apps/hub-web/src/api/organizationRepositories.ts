import { ApiError, apiClient } from "./client";
import type { RepositoryVisibility } from "./repositories";

export interface OrganizationRepository {
  id: string;
  name: string;
  description: string | null;
  visibility: RepositoryVisibility;
  created_at: string;
  updated_at: string;
}

export interface OrganizationRepositoryListResponse {
  items: OrganizationRepository[];
  total: number;
  limit: number;
  offset: number;
}

export interface OrganizationRepositoryInput {
  name: string;
  description?: string | null;
  visibility?: RepositoryVisibility;
}

export interface OrganizationRepositoryUpdateInput {
  name?: string;
  description?: string | null;
  visibility?: RepositoryVisibility;
}

function requireResponse<T>(response: T | undefined, message: string): T {
  if (response !== undefined) return response;
  throw new ApiError(message, { status: 200, code: "invalid_response", requestId: null });
}

function repositoryPath(organizationId: string, repositoryId?: string): string {
  const base = `/organizations/${encodeURIComponent(organizationId)}/repositories`;
  return repositoryId ? `${base}/${encodeURIComponent(repositoryId)}` : base;
}

export async function listOrganizationRepositories(
  organizationId: string,
  limit = 50,
  offset = 0,
  options: { signal?: AbortSignal } = {},
): Promise<OrganizationRepositoryListResponse> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return requireResponse(
    await apiClient.get<OrganizationRepositoryListResponse>(
      `${repositoryPath(organizationId)}?${query}`,
      options,
    ),
    "The Hub API returned an empty organization repository response.",
  );
}

export async function createOrganizationRepository(
  organizationId: string,
  input: OrganizationRepositoryInput,
): Promise<OrganizationRepository> {
  return requireResponse(
    await apiClient.post<OrganizationRepository, OrganizationRepositoryInput>(
      repositoryPath(organizationId),
      { ...input, visibility: input.visibility ?? "private" },
    ),
    "The Hub API returned an empty organization repository response.",
  );
}

export async function getOrganizationRepository(
  organizationId: string,
  repositoryId: string,
  options: { signal?: AbortSignal } = {},
): Promise<OrganizationRepository> {
  return requireResponse(
    await apiClient.get<OrganizationRepository>(
      repositoryPath(organizationId, repositoryId),
      options,
    ),
    "The Hub API returned an empty organization repository response.",
  );
}

export async function updateOrganizationRepository(
  organizationId: string,
  repositoryId: string,
  input: OrganizationRepositoryUpdateInput,
): Promise<OrganizationRepository> {
  return requireResponse(
    await apiClient.patch<OrganizationRepository, OrganizationRepositoryUpdateInput>(
      repositoryPath(organizationId, repositoryId),
      input,
    ),
    "The Hub API returned an empty organization repository response.",
  );
}

export async function deleteOrganizationRepository(
  organizationId: string,
  repositoryId: string,
): Promise<void> {
  await apiClient.delete<void>(repositoryPath(organizationId, repositoryId));
}
