import { ApiError, apiClient } from "./client";

export type OrganizationRole = "owner" | "admin" | "member";
export type MembershipRole = "admin" | "member";

export interface Organization {
  id: string;
  slug: string;
  name: string;
  state: string;
  role: OrganizationRole | null;
  created_at: string;
  updated_at: string;
}

export interface OrganizationListResponse {
  items: Organization[];
  total: number;
  limit: number;
  offset: number;
}

export interface Membership {
  user_id: string;
  role: OrganizationRole;
  joined_at: string;
}

export interface MembershipListResponse {
  items: Membership[];
  total: number;
  limit: number;
  offset: number;
}

export interface OrganizationInvitation {
  id: string;
  target_email: string;
  role: MembershipRole;
  status: "pending" | "accepted" | "revoked" | "expired";
  expires_at: string;
  created_at: string;
}

export interface OrganizationInvitationCreate extends OrganizationInvitation {
  token: string;
}

export interface OrganizationInvitationListResponse {
  items: OrganizationInvitation[];
  total: number;
  limit: number;
  offset: number;
}

export interface OrganizationMutationOptions {
  signal?: AbortSignal;
  limit?: number;
  offset?: number;
}

export interface OrganizationInput {
  slug: string;
  name: string;
}

export interface OrganizationUpdateInput {
  slug?: string;
  name?: string;
}

function requireResponse<T>(response: T | undefined, message: string): T {
  if (response !== undefined) return response;
  throw new ApiError(message, { status: 200, code: "invalid_response", requestId: null });
}

function organizationPath(organizationId: string): string {
  return `/organizations/${encodeURIComponent(organizationId)}`;
}

export async function listOrganizations(
  options: OrganizationMutationOptions = {},
): Promise<OrganizationListResponse> {
  const query = new URLSearchParams({
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0),
  });
  return requireResponse(
    await apiClient.get<OrganizationListResponse>(`/organizations?${query}`, options),
    "The Hub API returned an empty organization response.",
  );
}

export async function createOrganization(input: OrganizationInput): Promise<Organization> {
  return requireResponse(
    await apiClient.post<Organization, OrganizationInput>("/organizations", input),
    "The Hub API returned an empty organization response.",
  );
}

export async function getOrganization(
  organizationId: string,
  options: OrganizationMutationOptions = {},
): Promise<Organization> {
  return requireResponse(
    await apiClient.get<Organization>(organizationPath(organizationId), options),
    "The Hub API returned an empty organization response.",
  );
}

export async function updateOrganization(
  organizationId: string,
  input: OrganizationUpdateInput,
): Promise<Organization> {
  return requireResponse(
    await apiClient.patch<Organization, OrganizationUpdateInput>(
      organizationPath(organizationId),
      input,
    ),
    "The Hub API returned an empty organization response.",
  );
}

export async function listOrganizationMembers(
  organizationId: string,
  options: OrganizationMutationOptions = {},
): Promise<MembershipListResponse> {
  const query = new URLSearchParams({
    limit: String(options.limit ?? 100),
    offset: String(options.offset ?? 0),
  });
  return requireResponse(
    await apiClient.get<MembershipListResponse>(
      `${organizationPath(organizationId)}/members?${query}`,
      options,
    ),
    "The Hub API returned an empty membership response.",
  );
}

export async function addOrganizationMember(
  organizationId: string,
  userId: string,
  role: MembershipRole,
): Promise<Membership> {
  return requireResponse(
    await apiClient.post<Membership, { user_id: string; role: MembershipRole }>(
      `${organizationPath(organizationId)}/members`,
      { user_id: userId, role },
    ),
    "The Hub API returned an empty membership response.",
  );
}

export async function changeOrganizationMemberRole(
  organizationId: string,
  userId: string,
  role: MembershipRole,
): Promise<Membership> {
  return requireResponse(
    await apiClient.patch<Membership, { role: MembershipRole }>(
      `${organizationPath(organizationId)}/members/${encodeURIComponent(userId)}`,
      { role },
    ),
    "The Hub API returned an empty membership response.",
  );
}

export async function removeOrganizationMember(
  organizationId: string,
  userId: string,
): Promise<void> {
  await apiClient.delete<void>(
    `${organizationPath(organizationId)}/members/${encodeURIComponent(userId)}`,
  );
}

export async function leaveOrganization(organizationId: string): Promise<void> {
  await apiClient.post(`${organizationPath(organizationId)}/leave`);
}

export async function transferOrganizationOwnership(
  organizationId: string,
  targetUserId: string,
  currentPassword: string,
): Promise<void> {
  await apiClient.post(`${organizationPath(organizationId)}/transfer-ownership`, {
    target_user_id: targetUserId,
    current_password: currentPassword,
  });
}

export async function listOrganizationInvitations(
  organizationId: string,
  options: OrganizationMutationOptions = {},
): Promise<OrganizationInvitationListResponse> {
  const query = new URLSearchParams({
    limit: String(options.limit ?? 100),
    offset: String(options.offset ?? 0),
  });
  return requireResponse(
    await apiClient.get<OrganizationInvitationListResponse>(
      `${organizationPath(organizationId)}/invitations?${query}`,
      options,
    ),
    "The Hub API returned an empty invitation response.",
  );
}

export async function createOrganizationInvitation(
  organizationId: string,
  targetEmail: string,
  role: MembershipRole,
  expiresInDays = 7,
): Promise<OrganizationInvitationCreate> {
  return requireResponse(
    await apiClient.post<
      OrganizationInvitationCreate,
      { target_email: string; role: MembershipRole; expires_in_days: number }
    >(`${organizationPath(organizationId)}/invitations`, {
      target_email: targetEmail,
      role,
      expires_in_days: expiresInDays,
    }),
    "The Hub API returned an empty invitation response.",
  );
}

export async function revokeOrganizationInvitation(
  organizationId: string,
  invitationId: string,
): Promise<void> {
  await apiClient.delete<void>(
    `${organizationPath(organizationId)}/invitations/${encodeURIComponent(invitationId)}`,
  );
}

export async function acceptOrganizationInvitation(token: string): Promise<{
  organization_id: string;
  role: OrganizationRole;
}> {
  return requireResponse(
    await apiClient.post<{ organization_id: string; role: OrganizationRole }>(
      `/invitations/${encodeURIComponent(token)}/accept`,
    ),
    "The Hub API returned an empty invitation acceptance response.",
  );
}
