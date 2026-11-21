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

export interface RepositorySearchResponse {
  items: PersonalRepository[];
  total: number;
}

export interface RepositoryActivity {
  id: string;
  action: string;
  target_type: string;
  target_id: string;
  occurred_at: string;
  metadata: Record<string, unknown>;
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

export type DirectRepositoryRole = "reader" | "writer" | "admin";

export interface RepositoryPermission {
  user_id: string;
  role: DirectRepositoryRole;
  created_at: string;
  updated_at: string;
}

export interface RepositoryInvitation {
  id: string;
  target_email: string;
  role: DirectRepositoryRole;
  status: string;
  expires_at: string;
  created_at: string;
}

export interface CreatedRepositoryInvitation extends RepositoryInvitation {
  token: string;
}

export interface RepositoryInvitationListResponse {
  items: RepositoryInvitation[];
  total: number;
  limit: number;
  offset: number;
}

export interface RepositoryInvitationAcceptResponse {
  repository_id: string;
  role: DirectRepositoryRole;
}

export interface RepositoryReadOptions {
  signal?: AbortSignal;
  limit?: number;
  offset?: number;
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

export async function searchRepositories(
  query: string,
  params: RepositoryListParams = {},
): Promise<RepositorySearchResponse> {
  const { limit, offset } = normalizeRepositoryListParams(params);
  const search = new URLSearchParams({
    query,
    limit: String(limit),
    offset: String(offset),
  });
  return requireResponse(
    await apiClient.get<RepositorySearchResponse>(`/repositories/search?${search}`),
  );
}

export async function getRepositoryActivity(limit = 50): Promise<RepositoryActivity[]> {
  return requireResponse(
    await apiClient.get<RepositoryActivity[]>(`/repositories/activity?limit=${limit}`),
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

export async function listRepositoryPermissions(
  repositoryId: string,
  options: RepositoryReadOptions = {},
): Promise<RepositoryPermission[]> {
  return requireResponse(
    await apiClient.get<RepositoryPermission[]>(
      `${repositoryPath(repositoryId)}/permissions`,
      options,
    ),
  );
}

export async function grantRepositoryPermission(
  repositoryId: string,
  userId: string,
  role: DirectRepositoryRole,
): Promise<RepositoryPermission> {
  return requireResponse(
    await apiClient.post<RepositoryPermission, { user_id: string; role: DirectRepositoryRole }>(
      `${repositoryPath(repositoryId)}/permissions`,
      { user_id: userId, role },
    ),
  );
}

export async function updateRepositoryPermission(
  repositoryId: string,
  userId: string,
  role: DirectRepositoryRole,
): Promise<RepositoryPermission> {
  return requireResponse(
    await apiClient.patch<RepositoryPermission, { role: DirectRepositoryRole }>(
      `${repositoryPath(repositoryId)}/permissions/${encodeURIComponent(userId)}`,
      { role },
    ),
  );
}

export async function revokeRepositoryPermission(
  repositoryId: string,
  userId: string,
): Promise<void> {
  await apiClient.delete<void>(
    `${repositoryPath(repositoryId)}/permissions/${encodeURIComponent(userId)}`,
  );
}

export async function createRepositoryInvitation(
  repositoryId: string,
  targetEmail: string,
  role: DirectRepositoryRole,
  expiresInDays = 7,
): Promise<CreatedRepositoryInvitation> {
  return requireResponse(
    await apiClient.post<
      CreatedRepositoryInvitation,
      { target_email: string; role: DirectRepositoryRole; expires_in_days: number }
    >(`${repositoryPath(repositoryId)}/invitations`, {
      target_email: targetEmail,
      role,
      expires_in_days: expiresInDays,
    }),
  );
}

export async function listRepositoryInvitations(
  repositoryId: string,
  options: RepositoryReadOptions = {},
): Promise<RepositoryInvitationListResponse> {
  const query = new URLSearchParams({
    limit: String(options.limit ?? 100),
    offset: String(options.offset ?? 0),
  });
  return requireResponse(
    await apiClient.get<RepositoryInvitationListResponse>(
      `${repositoryPath(repositoryId)}/invitations?${query}`,
      options,
    ),
  );
}

export async function revokeRepositoryInvitation(
  repositoryId: string,
  invitationId: string,
): Promise<void> {
  await apiClient.delete<void>(
    `${repositoryPath(repositoryId)}/invitations/${encodeURIComponent(invitationId)}`,
  );
}

export async function acceptRepositoryInvitation(
  token: string,
): Promise<RepositoryInvitationAcceptResponse> {
  return requireResponse(
    await apiClient.post<RepositoryInvitationAcceptResponse>(
      `/repositories/invitations/${encodeURIComponent(token)}/accept`,
    ),
  );
}
