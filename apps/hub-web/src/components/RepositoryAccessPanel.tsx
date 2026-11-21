import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/client";
import {
  getProtectedQueryIdentityGeneration,
  isProtectedQueryIdentity,
  protectedQueryKey,
} from "../app/protectedQueryCache";
import {
  createRepositoryInvitation,
  grantRepositoryPermission,
  listRepositoryInvitations,
  listRepositoryPermissions,
  revokeRepositoryInvitation,
  revokeRepositoryPermission,
  updateRepositoryPermission,
  type CreatedRepositoryInvitation,
  type DirectRepositoryRole,
} from "../api/repositories";
import { searchUsers, type UserSearchResult } from "../api/users";

interface MutationIdentity {
  generation: number;
}

interface PermissionMutationIdentity extends MutationIdentity {
  userId: string;
  role?: DirectRepositoryRole;
}

interface InvitationMutationIdentity extends MutationIdentity {
  email?: string;
  role?: DirectRepositoryRole;
  expiresInDays?: number;
  invitationId?: string;
}

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "The repository access request failed.";
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
}

export function RepositoryAccessPanel({
  repositoryId,
  userId,
}: {
  repositoryId: string;
  userId: string;
}) {
  const queryClient = useQueryClient();
  const [searchText, setSearchText] = useState("");
  const [selectedUser, setSelectedUser] = useState<UserSearchResult | null>(null);
  const [knownUsers, setKnownUsers] = useState<Record<string, UserSearchResult>>({});
  const [permissionRole, setPermissionRole] = useState<DirectRepositoryRole>("reader");
  const [invitationEmail, setInvitationEmail] = useState("");
  const [invitationRole, setInvitationRole] = useState<DirectRepositoryRole>("reader");
  const [invitationExpiresInDays, setInvitationExpiresInDays] = useState(7);
  const [invitationOffset, setInvitationOffset] = useState(0);
  const [latestInvitation, setLatestInvitation] = useState<CreatedRepositoryInvitation | null>(
    null,
  );
  const [copyMessage, setCopyMessage] = useState("");
  const [confirmingPermissionId, setConfirmingPermissionId] = useState<string | null>(null);
  const [confirmingInvitationId, setConfirmingInvitationId] = useState<string | null>(null);
  const queryPrefix = protectedQueryKey(userId, "repositories", repositoryId);
  const permissionsQuery = useQuery({
    queryKey: [...queryPrefix, "permissions"],
    queryFn: ({ signal }) => listRepositoryPermissions(repositoryId, { signal }),
    enabled: Boolean(userId && repositoryId),
  });
  const invitationsQuery = useQuery({
    queryKey: [...queryPrefix, "invitations", invitationOffset],
    queryFn: ({ signal }) =>
      listRepositoryInvitations(repositoryId, {
        signal,
        limit: 100,
        offset: invitationOffset,
      }),
    enabled: Boolean(userId && repositoryId),
  });
  const normalizedSearch = searchText.trim();
  const userSearchQuery = useQuery({
    queryKey: protectedQueryKey(userId, "users", "search", normalizedSearch),
    queryFn: ({ signal }) => searchUsers(normalizedSearch, { signal }),
    enabled: normalizedSearch.length >= 2 && !selectedUser,
  });
  const isCurrent = (generation: number) =>
    isProtectedQueryIdentity(queryClient, userId, generation);
  const invalidateAccess = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: [...queryPrefix, "permissions"] }),
      queryClient.invalidateQueries({ queryKey: [...queryPrefix, "invitations"] }),
    ]);
  };
  const grantMutation = useMutation({
    mutationKey: [...queryPrefix, "mutation", "permission", "grant"],
    mutationFn: ({ userId: targetId, role }: PermissionMutationIdentity) =>
      grantRepositoryPermission(repositoryId, targetId, role ?? "reader"),
    retry: false,
    onSuccess: async (_permission, variables) => {
      if (!isCurrent(variables.generation)) return;
      await invalidateAccess();
      if (!isCurrent(variables.generation)) return;
      setSelectedUser(null);
      setSearchText("");
    },
  });
  const updatePermissionMutation = useMutation({
    mutationKey: [...queryPrefix, "mutation", "permission", "update"],
    mutationFn: ({ userId: targetId, role }: PermissionMutationIdentity) =>
      updateRepositoryPermission(repositoryId, targetId, role ?? "reader"),
    retry: false,
    onSuccess: async (_permission, variables) => {
      if (!isCurrent(variables.generation)) return;
      await invalidateAccess();
    },
  });
  const revokePermissionMutation = useMutation({
    mutationKey: [...queryPrefix, "mutation", "permission", "revoke"],
    mutationFn: ({ userId: targetId }: PermissionMutationIdentity) =>
      revokeRepositoryPermission(repositoryId, targetId),
    retry: false,
    onSuccess: async (_result, variables) => {
      if (!isCurrent(variables.generation)) return;
      await invalidateAccess();
      if (!isCurrent(variables.generation)) return;
      setConfirmingPermissionId(null);
    },
  });
  const createInvitationMutation = useMutation({
    mutationKey: [...queryPrefix, "mutation", "invitation", "create"],
    mutationFn: ({ email, role, expiresInDays }: InvitationMutationIdentity) =>
      createRepositoryInvitation(repositoryId, email ?? "", role ?? "reader", expiresInDays ?? 7),
    retry: false,
    onSuccess: async (invitation, variables) => {
      if (!isCurrent(variables.generation)) return;
      setInvitationOffset(0);
      await invalidateAccess();
      if (!isCurrent(variables.generation)) return;
      setLatestInvitation(invitation);
      setInvitationEmail("");
      setCopyMessage("");
    },
  });
  const revokeInvitationMutation = useMutation({
    mutationKey: [...queryPrefix, "mutation", "invitation", "revoke"],
    mutationFn: ({ invitationId }: InvitationMutationIdentity) =>
      revokeRepositoryInvitation(repositoryId, invitationId ?? ""),
    retry: false,
    onSuccess: async (_result, variables) => {
      if (!isCurrent(variables.generation)) return;
      setInvitationOffset(0);
      await invalidateAccess();
      if (!isCurrent(variables.generation)) return;
      setConfirmingInvitationId(null);
    },
  });

  function currentGeneration(): number | null {
    return getProtectedQueryIdentityGeneration(queryClient, userId);
  }

  function chooseUser(candidate: UserSearchResult) {
    setSelectedUser(candidate);
    setKnownUsers((current) => ({ ...current, [candidate.id]: candidate }));
    setSearchText("");
  }

  async function copyInvitationToken() {
    if (!latestInvitation) return;
    if (!navigator.clipboard) {
      setCopyMessage("Clipboard access is unavailable. Select and copy the token manually.");
      return;
    }
    try {
      await navigator.clipboard.writeText(latestInvitation.token);
      setCopyMessage("Invitation token copied.");
    } catch {
      setCopyMessage("Could not copy the token. Select and copy it manually.");
    }
  }

  const mutationErrors = [
    grantMutation.error,
    updatePermissionMutation.error,
    revokePermissionMutation.error,
    createInvitationMutation.error,
    revokeInvitationMutation.error,
  ].filter((error): error is Error => error !== null);

  return (
    <section
      className="repository-form-section repository-access-section"
      aria-labelledby="access-title"
    >
      <div className="repository-section-heading">
        <h2 id="access-title">Repository access</h2>
        <p>Direct access is separate from organization membership.</p>
      </div>

      {permissionsQuery.isPending ? (
        <p className="repository-state" role="status">
          Loading direct permissions…
        </p>
      ) : null}
      {permissionsQuery.isError ? (
        <div className="repository-form-error" role="alert">
          <p>
            {errorMessage(permissionsQuery.error)}
            {permissionsQuery.data ? " Showing the last loaded permissions." : ""}
          </p>
          <button type="button" onClick={() => void permissionsQuery.refetch()}>
            Retry permissions
          </button>
        </div>
      ) : null}
      {permissionsQuery.data?.length === 0 ? (
        <p className="repository-state">No direct collaborators have access yet.</p>
      ) : null}
      {permissionsQuery.data?.length ? (
        <ul className="repository-list" aria-label="Direct repository permissions">
          {permissionsQuery.data.map((permission) => {
            const profile = knownUsers[permission.user_id];
            const label =
              permission.user_id === userId
                ? "You"
                : profile
                  ? `${profile.display_name} (@${profile.username})`
                  : `Account ${permission.user_id.slice(0, 8)}`;
            return (
              <li className="repository-list-item" key={permission.user_id}>
                <div className="repository-list-main">
                  <span className="repository-name-link">{label}</span>
                  <code className="repository-access-user-id">{permission.user_id}</code>
                </div>
                <div className="organization-member-actions">
                  <label className="sr-only" htmlFor={`permission-role-${permission.user_id}`}>
                    Access role for {label}
                  </label>
                  <select
                    id={`permission-role-${permission.user_id}`}
                    value={permission.role}
                    disabled={updatePermissionMutation.isPending}
                    onChange={(event) => {
                      const generation = currentGeneration();
                      if (generation === null) return;
                      updatePermissionMutation.mutate({
                        userId: permission.user_id,
                        role: event.currentTarget.value as DirectRepositoryRole,
                        generation,
                      });
                    }}
                  >
                    <option value="reader">Reader</option>
                    <option value="writer">Writer</option>
                    <option value="admin">Admin</option>
                  </select>
                  {confirmingPermissionId === permission.user_id ? (
                    <>
                      <span>Revoke access?</span>
                      <button
                        className="repository-danger-action"
                        type="button"
                        disabled={revokePermissionMutation.isPending}
                        onClick={() => {
                          const generation = currentGeneration();
                          if (generation !== null) {
                            revokePermissionMutation.mutate({
                              userId: permission.user_id,
                              generation,
                            });
                          }
                        }}
                      >
                        Confirm revoke
                      </button>
                      <button
                        className="repository-secondary-action"
                        type="button"
                        disabled={revokePermissionMutation.isPending}
                        onClick={() => setConfirmingPermissionId(null)}
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <button
                      className="repository-danger-action"
                      type="button"
                      disabled={revokePermissionMutation.isPending}
                      onClick={() => setConfirmingPermissionId(permission.user_id)}
                    >
                      Revoke access
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      ) : null}

      <div className="organization-inline-form repository-access-grant">
        <label className="sr-only" htmlFor="repository-user-search">
          Search users to grant repository access
        </label>
        <input
          id="repository-user-search"
          value={
            selectedUser ? `${selectedUser.display_name} (@${selectedUser.username})` : searchText
          }
          placeholder="Search a user by name or username"
          onChange={(event) => {
            setSelectedUser(null);
            setSearchText(event.currentTarget.value);
          }}
        />
        <label className="sr-only" htmlFor="repository-grant-role">
          Direct access role
        </label>
        <select
          id="repository-grant-role"
          value={permissionRole}
          onChange={(event) => setPermissionRole(event.currentTarget.value as DirectRepositoryRole)}
        >
          <option value="reader">Reader</option>
          <option value="writer">Writer</option>
          <option value="admin">Admin</option>
        </select>
        <button
          className="repository-primary-action"
          type="button"
          disabled={!selectedUser || grantMutation.isPending}
          onClick={() => {
            const generation = currentGeneration();
            if (generation !== null && selectedUser) {
              grantMutation.mutate({
                userId: selectedUser.id,
                role: permissionRole,
                generation,
              });
            }
          }}
        >
          {grantMutation.isPending ? "Granting…" : "Grant access"}
        </button>
      </div>
      {normalizedSearch.length >= 2 && userSearchQuery.isFetching ? (
        <p className="repository-state" role="status">
          Searching active profiles…
        </p>
      ) : null}
      {userSearchQuery.isError ? (
        <p className="repository-state-error" role="alert">
          {errorMessage(userSearchQuery.error)}
        </p>
      ) : null}
      {userSearchQuery.data?.items.length ? (
        <ul className="organization-user-suggestions" aria-label="User search results">
          {userSearchQuery.data.items.map((candidate) => (
            <li key={candidate.id}>
              <button
                className="repository-secondary-action"
                type="button"
                onClick={() => chooseUser(candidate)}
              >
                {candidate.display_name} (@{candidate.username})
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {normalizedSearch.length >= 2 &&
      userSearchQuery.isSuccess &&
      userSearchQuery.data.items.length === 0 ? (
        <p className="repository-state">No active profile matched that search.</p>
      ) : null}
      {mutationErrors.map((error, index) => (
        <p className="repository-state-error" role="alert" key={`${error.message}-${index}`}>
          {errorMessage(error)}
        </p>
      ))}

      <div className="repository-access-invite">
        <h3>Invite by email</h3>
        <p>
          Repository invitations grant the selected direct role and must be accepted by that
          account.
        </p>
        <form
          className="organization-inline-form"
          onSubmit={(event) => {
            event.preventDefault();
            const generation = currentGeneration();
            if (generation !== null) {
              createInvitationMutation.mutate({
                email: invitationEmail.trim(),
                role: invitationRole,
                expiresInDays: invitationExpiresInDays,
                generation,
              });
            }
          }}
        >
          <label className="sr-only" htmlFor="repository-invitation-email">
            Invitation email
          </label>
          <input
            id="repository-invitation-email"
            type="email"
            required
            autoComplete="email"
            value={invitationEmail}
            onChange={(event) => setInvitationEmail(event.currentTarget.value)}
            placeholder="developer@example.com"
          />
          <label className="sr-only" htmlFor="repository-invitation-role">
            Invitation role
          </label>
          <select
            id="repository-invitation-role"
            value={invitationRole}
            onChange={(event) =>
              setInvitationRole(event.currentTarget.value as DirectRepositoryRole)
            }
          >
            <option value="reader">Reader</option>
            <option value="writer">Writer</option>
            <option value="admin">Admin</option>
          </select>
          <label className="sr-only" htmlFor="repository-invitation-expiry">
            Invitation expiration
          </label>
          <select
            id="repository-invitation-expiry"
            value={invitationExpiresInDays}
            onChange={(event) => setInvitationExpiresInDays(Number(event.currentTarget.value))}
          >
            <option value={7}>Expires in 7 days</option>
            <option value={14}>Expires in 14 days</option>
            <option value={30}>Expires in 30 days</option>
          </select>
          <button
            className="repository-primary-action"
            type="submit"
            disabled={!invitationEmail.trim() || createInvitationMutation.isPending}
          >
            {createInvitationMutation.isPending ? "Creating…" : "Create invitation"}
          </button>
        </form>
      </div>
      {latestInvitation ? (
        <div className="organization-invitation-token" role="status">
          <p>
            Share this one-time token with {latestInvitation.target_email}. It is only shown once.
          </p>
          <code>{latestInvitation.token}</code>
          <button
            className="repository-secondary-action"
            type="button"
            onClick={() => void copyInvitationToken()}
          >
            Copy token
          </button>
          {copyMessage ? <p>{copyMessage}</p> : null}
        </div>
      ) : null}

      {invitationsQuery.isPending ? (
        <p className="repository-state" role="status">
          Loading repository invitations…
        </p>
      ) : null}
      {invitationsQuery.isError ? (
        <div className="repository-form-error" role="alert">
          <p>
            {errorMessage(invitationsQuery.error)}
            {invitationsQuery.data ? " Showing the last loaded invitations." : ""}
          </p>
          <button type="button" onClick={() => void invitationsQuery.refetch()}>
            Retry invitations
          </button>
        </div>
      ) : null}
      {invitationsQuery.data?.items.length === 0 && invitationOffset === 0 ? (
        <p className="repository-state">No pending repository invitations.</p>
      ) : null}
      {invitationsQuery.data?.items.length === 0 && invitationOffset > 0 ? (
        <p className="repository-state">No invitations are available on this page.</p>
      ) : null}
      {invitationsQuery.data?.items.length ? (
        <ul className="repository-list" aria-label="Pending repository invitations">
          {invitationsQuery.data.items.map((invitation) => (
            <li className="repository-list-item" key={invitation.id}>
              <div className="repository-list-main">
                <span className="repository-name-link">{invitation.target_email}</span>
                <p>
                  {invitation.role} · expires{" "}
                  <time dateTime={invitation.expires_at}>{formatDate(invitation.expires_at)}</time>
                </p>
              </div>
              {confirmingInvitationId === invitation.id ? (
                <div className="organization-member-actions">
                  <span>Revoke this invitation?</span>
                  <button
                    className="repository-danger-action"
                    type="button"
                    disabled={revokeInvitationMutation.isPending}
                    onClick={() => {
                      const generation = currentGeneration();
                      if (generation !== null) {
                        revokeInvitationMutation.mutate({
                          invitationId: invitation.id,
                          generation,
                        });
                      }
                    }}
                  >
                    Confirm revoke
                  </button>
                  <button
                    className="repository-secondary-action"
                    type="button"
                    disabled={revokeInvitationMutation.isPending}
                    onClick={() => setConfirmingInvitationId(null)}
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  className="repository-danger-action"
                  type="button"
                  disabled={revokeInvitationMutation.isPending}
                  onClick={() => setConfirmingInvitationId(invitation.id)}
                >
                  Revoke invitation
                </button>
              )}
            </li>
          ))}
        </ul>
      ) : null}
      {invitationsQuery.data &&
      (invitationsQuery.data.total > invitationsQuery.data.limit || invitationOffset > 0) ? (
        <nav className="repository-pagination" aria-label="Repository invitation pages">
          <button
            className="repository-secondary-action"
            type="button"
            disabled={invitationOffset === 0 || invitationsQuery.isFetching}
            onClick={() =>
              setInvitationOffset((current) => Math.max(0, current - invitationsQuery.data.limit))
            }
          >
            Previous
          </button>
          <p>
            Showing {invitationOffset + 1}–{invitationOffset + invitationsQuery.data.items.length}{" "}
            of {invitationsQuery.data.total}
          </p>
          <button
            className="repository-secondary-action"
            type="button"
            disabled={
              invitationOffset + invitationsQuery.data.items.length >=
                invitationsQuery.data.total || invitationsQuery.isFetching
            }
            onClick={() => setInvitationOffset((current) => current + invitationsQuery.data.limit)}
          >
            Next
          </button>
        </nav>
      ) : null}
    </section>
  );
}
