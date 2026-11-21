import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  getProtectedQueryIdentityGeneration,
  isProtectedQueryIdentity,
  protectedQueryKey,
} from "../app/protectedQueryCache";
import { useAuth } from "../auth/AuthContext";
import {
  addOrganizationMember,
  createOrganizationInvitation,
  changeOrganizationMemberRole,
  getOrganization,
  listOrganizationInvitations,
  leaveOrganization,
  listOrganizationMembers,
  removeOrganizationMember,
  revokeOrganizationInvitation,
  transferOrganizationOwnership,
  updateOrganization,
  type MembershipRole,
  type Organization,
} from "../api/organizations";
import { OrganizationForm, type OrganizationFormValues } from "../components/OrganizationForm";
import { searchUsers } from "../api/users";

function asApiError(error: unknown): ApiError {
  return error instanceof ApiError
    ? error
    : new ApiError("The organization operation failed.", {
        status: null,
        code: "unexpected_error",
        requestId: null,
        cause: error,
      });
}

export function OrganizationDetailPage() {
  const { organizationId = "" } = useParams();
  const auth = useAuth();
  const userId = auth.status === "authenticated" ? auth.user.id : "";
  const queryClient = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const [memberUserId, setMemberUserId] = useState("");
  const [memberRole, setMemberRole] = useState<MembershipRole>("member");
  const [memberOffset, setMemberOffset] = useState(0);
  const [invitationEmail, setInvitationEmail] = useState("");
  const [invitationRole, setInvitationRole] = useState<MembershipRole>("member");
  const [invitationOffset, setInvitationOffset] = useState(0);
  const [latestInvitationToken, setLatestInvitationToken] = useState<string | null>(null);
  const [invitationCopyMessage, setInvitationCopyMessage] = useState("");
  const [confirmingMemberId, setConfirmingMemberId] = useState<string | null>(null);
  const [confirmingInvitationId, setConfirmingInvitationId] = useState<string | null>(null);
  const [confirmingLeave, setConfirmingLeave] = useState(false);
  const [transferUserId, setTransferUserId] = useState("");
  const [transferPassword, setTransferPassword] = useState("");
  const organizationQuery = useQuery({
    queryKey: protectedQueryKey(userId, "organizations", "detail", organizationId),
    queryFn: ({ signal }) => getOrganization(organizationId, { signal }),
    enabled: Boolean(userId && organizationId),
  });
  const canManage =
    organizationQuery.data?.role === "owner" || organizationQuery.data?.role === "admin";
  const isOwner = organizationQuery.data?.role === "owner";
  const membersQuery = useQuery({
    queryKey: protectedQueryKey(userId, "organizations", organizationId, "members", memberOffset),
    queryFn: ({ signal }) =>
      listOrganizationMembers(organizationId, { signal, limit: 100, offset: memberOffset }),
    enabled: Boolean(userId && organizationId),
  });
  const invitationsQuery = useQuery({
    queryKey: protectedQueryKey(
      userId,
      "organizations",
      organizationId,
      "invitations",
      invitationOffset,
    ),
    queryFn: ({ signal }) =>
      listOrganizationInvitations(organizationId, {
        signal,
        limit: 100,
        offset: invitationOffset,
      }),
    enabled: Boolean(userId && organizationId && canManage),
  });
  const userSearchQuery = useQuery({
    queryKey: protectedQueryKey(userId, "users", "search", memberUserId.trim()),
    queryFn: ({ signal }) => searchUsers(memberUserId.trim(), { signal }),
    enabled: Boolean(canManage && memberUserId.trim().length >= 2),
  });
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: protectedQueryKey(userId, "organizations"),
      }),
      queryClient.invalidateQueries({
        queryKey: protectedQueryKey(userId, "organizations", organizationId, "members"),
      }),
      queryClient.invalidateQueries({
        queryKey: protectedQueryKey(userId, "organizations", organizationId, "invitations"),
      }),
    ]);
  };
  const updateMutation = useMutation<Organization, ApiError, OrganizationFormValues>({
    mutationKey: protectedQueryKey(userId, "organizations", organizationId, "mutation", "update"),
    mutationFn: (values) => updateOrganization(organizationId, values),
    retry: false,
    onSuccess: invalidate,
  });
  const addMutation = useMutation({
    mutationKey: protectedQueryKey(
      userId,
      "organizations",
      organizationId,
      "mutation",
      "add-member",
    ),
    mutationFn: (role: MembershipRole) =>
      addOrganizationMember(organizationId, memberUserId.trim(), role),
    retry: false,
    onSuccess: async () => {
      setMemberUserId("");
      setMemberOffset(0);
      await invalidate();
    },
  });
  const invitationMutation = useMutation({
    mutationKey: protectedQueryKey(userId, "organizations", organizationId, "mutation", "invite"),
    mutationFn: () =>
      createOrganizationInvitation(
        organizationId,
        invitationEmail.trim(),
        organizationQuery.data?.role === "owner" ? invitationRole : "member",
      ),
    retry: false,
    onSuccess: async (invitation) => {
      setInvitationEmail("");
      setInvitationOffset(0);
      setLatestInvitationToken(invitation.token);
      await invalidate();
    },
  });
  const revokeInvitationMutation = useMutation({
    mutationKey: protectedQueryKey(
      userId,
      "organizations",
      organizationId,
      "mutation",
      "revoke-invitation",
    ),
    mutationFn: (invitationId: string) =>
      revokeOrganizationInvitation(organizationId, invitationId),
    retry: false,
    onSuccess: async () => {
      setConfirmingInvitationId(null);
      setInvitationOffset(0);
      await invalidate();
    },
  });
  const roleMutation = useMutation({
    mutationKey: protectedQueryKey(userId, "organizations", organizationId, "mutation", "role"),
    mutationFn: ({ id, role }: { id: string; role: MembershipRole }) =>
      changeOrganizationMemberRole(organizationId, id, role),
    retry: false,
    onSuccess: invalidate,
  });
  const removeMutation = useMutation({
    mutationKey: protectedQueryKey(
      userId,
      "organizations",
      organizationId,
      "mutation",
      "remove-member",
    ),
    mutationFn: (id: string) => removeOrganizationMember(organizationId, id),
    retry: false,
    onSuccess: async () => {
      setConfirmingMemberId(null);
      setMemberOffset(0);
      await invalidate();
    },
  });
  const leaveMutation = useMutation<void, ApiError, number>({
    mutationKey: protectedQueryKey(userId, "organizations", organizationId, "mutation", "leave"),
    mutationFn: () => leaveOrganization(organizationId),
    retry: false,
    onSuccess: async (_result, identityGeneration) => {
      if (!isProtectedQueryIdentity(queryClient, userId, identityGeneration)) return;
      await queryClient.invalidateQueries({
        queryKey: protectedQueryKey(userId, "organizations"),
      });
      if (!isProtectedQueryIdentity(queryClient, userId, identityGeneration)) return;
      void navigate("/app/organizations", { state: { focusDestinationHeading: true } });
    },
  });
  function leaveOrganizationFromCurrentSession() {
    const identityGeneration = getProtectedQueryIdentityGeneration(queryClient, userId);
    if (identityGeneration !== null) leaveMutation.mutate(identityGeneration);
  }
  async function copyInvitationToken() {
    if (!latestInvitationToken) return;
    if (!navigator.clipboard) {
      setInvitationCopyMessage(
        "Clipboard access is unavailable. Select and copy the token manually.",
      );
      return;
    }
    try {
      await navigator.clipboard.writeText(latestInvitationToken);
      setInvitationCopyMessage("Invitation token copied.");
    } catch {
      setInvitationCopyMessage("Could not copy the token. Select and copy it manually.");
    }
  }
  const transferMutation = useMutation({
    mutationKey: protectedQueryKey(
      userId,
      "organizations",
      organizationId,
      "mutation",
      "transfer-ownership",
    ),
    mutationFn: () =>
      transferOrganizationOwnership(organizationId, transferUserId.trim(), transferPassword),
    retry: false,
    onSuccess: async () => {
      setTransferUserId("");
      setTransferPassword("");
      await invalidate();
    },
  });
  const organization = organizationQuery.data;
  useEffect(() => {
    if (
      location.state &&
      typeof location.state === "object" &&
      "focusDestinationHeading" in location.state
    )
      document.getElementById("foundation-title")?.focus();
  }, [location.state, organizationQuery.isPending]);
  if (!userId) return null;
  if (organizationQuery.isPending)
    return (
      <main className="repository-page">
        <h1 id="foundation-title" tabIndex={-1}>
          Organization details
        </h1>
        <p className="repository-state" role="status">
          Loading organization…
        </p>
      </main>
    );
  if (!organization || organizationQuery.isError)
    return (
      <main className="repository-page">
        <h1 id="foundation-title" tabIndex={-1}>
          Organization unavailable
        </h1>
        <p className="repository-state-error" role="alert">
          {asApiError(organizationQuery.error).message}
        </p>
        <Link className="repository-secondary-action" to="/app/organizations">
          Back to organizations
        </Link>
      </main>
    );
  return (
    <main className="repository-page repository-form-page">
      <Link className="repository-back-link" to="/app/organizations">
        <span aria-hidden="true">←</span> All organizations
      </Link>
      <header className="repository-page-header repository-form-header">
        <div>
          <h1 id="foundation-title" tabIndex={-1}>
            {organization.name}
          </h1>
          <p className="repository-page-intro">
            {organization.slug} · {organization.state}
          </p>
        </div>
      </header>
      {canManage ? (
        <p className="organization-repository-link-row">
          <Link
            className="repository-secondary-action"
            to={`/app/organizations/${organizationId}/repositories`}
          >
            View organization repositories
          </Link>
        </p>
      ) : null}
      <section className="repository-form-section" aria-labelledby="organization-settings-title">
        <div className="repository-section-heading">
          <h2 id="organization-settings-title">Organization details</h2>
        </div>
        <OrganizationForm
          initialValues={{ slug: organization.slug, name: organization.name }}
          pending={updateMutation.isPending}
          submitLabel="Save changes"
          pendingLabel="Saving changes…"
          error={updateMutation.error}
          successMessage={updateMutation.isSuccess ? "Changes saved." : null}
          onValuesChange={() => updateMutation.reset()}
          onSubmit={(values) => updateMutation.mutate(values)}
        />
      </section>
      <section className="repository-form-section" aria-labelledby="organization-members-title">
        <div className="repository-section-heading">
          <h2 id="organization-members-title">Members</h2>
          <p>
            Membership changes are explicit; membership does not automatically grant repository
            access. Member names are not included in the membership API, so account identifiers are
            shown below.
          </p>
        </div>
        {membersQuery.isPending ? (
          <p className="repository-state" role="status">
            Loading members…
          </p>
        ) : null}
        {membersQuery.isError ? (
          <div className="repository-state-error" role="alert">
            <p>{asApiError(membersQuery.error).message}</p>
            <button
              className="repository-secondary-action"
              type="button"
              onClick={() => void membersQuery.refetch()}
            >
              Retry members
            </button>
          </div>
        ) : null}
        {membersQuery.data?.items.length === 0 && memberOffset === 0 ? (
          <p className="repository-state">No organization members were returned.</p>
        ) : null}
        {membersQuery.data?.items.length === 0 && memberOffset > 0 ? (
          <p className="repository-state">No organization members are available on this page.</p>
        ) : null}
        {membersQuery.data ? (
          <>
            <ul className="repository-list">
              {membersQuery.data.items.map((member) => (
                <li className="repository-list-item" key={member.user_id}>
                  <div className="repository-list-main">
                    <span className="repository-name-link">
                      Member account {member.user_id.slice(0, 8)}
                    </span>
                    <code className="repository-access-user-id">{member.user_id}</code>
                    <p>Joined {new Date(member.joined_at).toLocaleDateString()}</p>
                  </div>
                  <div className="organization-member-actions">
                    <span className="repository-visibility-tag">{member.role}</span>
                    {canManage && member.user_id !== userId && member.role !== "owner" ? (
                      <>
                        {isOwner ? (
                          <button
                            className="repository-secondary-action"
                            type="button"
                            onClick={() =>
                              roleMutation.mutate({
                                id: member.user_id,
                                role: member.role === "admin" ? "member" : "admin",
                              })
                            }
                          >
                            {member.role === "admin" ? "Make member" : "Make admin"}
                          </button>
                        ) : null}
                        {isOwner || member.role === "member" ? (
                          confirmingMemberId === member.user_id ? (
                            <>
                              <span>Remove this member?</span>
                              <button
                                className="repository-danger-action"
                                type="button"
                                disabled={removeMutation.isPending}
                                onClick={() => removeMutation.mutate(member.user_id)}
                              >
                                Confirm removal
                              </button>
                              <button
                                className="repository-secondary-action"
                                type="button"
                                disabled={removeMutation.isPending}
                                onClick={() => setConfirmingMemberId(null)}
                              >
                                Cancel
                              </button>
                            </>
                          ) : (
                            <button
                              className="repository-danger-action"
                              type="button"
                              onClick={() => setConfirmingMemberId(member.user_id)}
                            >
                              Remove
                            </button>
                          )
                        ) : null}
                      </>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
            {membersQuery.data.total > membersQuery.data.limit || memberOffset > 0 ? (
              <nav className="repository-pagination" aria-label="Organization member pages">
                <button
                  className="repository-secondary-action"
                  type="button"
                  disabled={memberOffset === 0 || membersQuery.isFetching}
                  onClick={() =>
                    setMemberOffset((current) => Math.max(0, current - membersQuery.data.limit))
                  }
                >
                  Previous
                </button>
                <p>
                  Showing {memberOffset + 1}–{memberOffset + membersQuery.data.items.length} of{" "}
                  {membersQuery.data.total}
                </p>
                <button
                  className="repository-secondary-action"
                  type="button"
                  disabled={
                    memberOffset + membersQuery.data.items.length >= membersQuery.data.total ||
                    membersQuery.isFetching
                  }
                  onClick={() => setMemberOffset((current) => current + membersQuery.data.limit)}
                >
                  Next
                </button>
              </nav>
            ) : null}
          </>
        ) : null}
      </section>
      {canManage ? (
        <section
          className="repository-form-section"
          aria-labelledby="organization-add-member-title"
        >
          <div className="repository-section-heading">
            <h2 id="organization-add-member-title">Add a member</h2>
            <p>Search active public profiles or paste an existing account user ID.</p>
          </div>
          <div className="organization-inline-form">
            <input
              aria-label="Member user ID"
              placeholder="User ID"
              value={memberUserId}
              onChange={(event) => setMemberUserId(event.currentTarget.value)}
            />
            <select
              aria-label="Member role"
              value={memberRole}
              onChange={(event) => setMemberRole(event.currentTarget.value as MembershipRole)}
            >
              <option value="member">Member</option>
              {isOwner ? <option value="admin">Admin</option> : null}
            </select>
            <button
              className="repository-primary-action"
              type="button"
              disabled={!memberUserId.trim() || addMutation.isPending}
              onClick={() => addMutation.mutate(isOwner ? memberRole : "member")}
            >
              {addMutation.isPending ? "Adding…" : "Add member"}
            </button>
          </div>
          {memberUserId.trim().length >= 2 && userSearchQuery.isFetching ? (
            <p className="repository-state" role="status">
              Searching public profiles…
            </p>
          ) : null}
          {userSearchQuery.data?.items.length ? (
            <ul className="organization-user-suggestions" aria-label="User suggestions">
              {userSearchQuery.data.items.map((candidate) => (
                <li key={candidate.id}>
                  <button
                    className="repository-secondary-action"
                    type="button"
                    onClick={() => setMemberUserId(candidate.id)}
                  >
                    {candidate.display_name} (@{candidate.username})
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          {addMutation.error ? (
            <p className="repository-state-error" role="alert">
              {asApiError(addMutation.error).message}
            </p>
          ) : null}
          {roleMutation.error || removeMutation.error ? (
            <p className="repository-state-error" role="alert">
              {asApiError(roleMutation.error ?? removeMutation.error).message}
            </p>
          ) : null}
        </section>
      ) : null}
      {canManage ? (
        <section
          className="repository-form-section"
          aria-labelledby="organization-invitations-title"
        >
          <div className="repository-section-heading">
            <h2 id="organization-invitations-title">Invite someone</h2>
            <p>
              Invitation tokens are shown once for manual sharing; no email service is configured.
            </p>
          </div>
          <div className="organization-inline-form">
            <input
              aria-label="Invitation email"
              type="email"
              placeholder="developer@example.com"
              value={invitationEmail}
              onChange={(event) => {
                setInvitationEmail(event.currentTarget.value);
                invitationMutation.reset();
                setInvitationCopyMessage("");
              }}
            />
            <select
              aria-label="Invitation role"
              value={invitationRole}
              onChange={(event) => setInvitationRole(event.currentTarget.value as MembershipRole)}
            >
              <option value="member">Member</option>
              {organization.role === "owner" ? <option value="admin">Admin</option> : null}
            </select>
            <button
              className="repository-primary-action"
              type="button"
              disabled={!invitationEmail.trim() || invitationMutation.isPending}
              onClick={() => invitationMutation.mutate()}
            >
              {invitationMutation.isPending ? "Creating…" : "Create invitation"}
            </button>
          </div>
          {invitationMutation.error ? (
            <p className="repository-state-error" role="alert">
              {asApiError(invitationMutation.error).message}
            </p>
          ) : null}
          {latestInvitationToken ? (
            <div className="organization-invitation-token" role="status">
              <p>Copy this one-time token before leaving the page.</p>
              <code>{latestInvitationToken}</code>
              <button
                className="repository-secondary-action"
                type="button"
                onClick={() => void copyInvitationToken()}
              >
                Copy token
              </button>
              {invitationCopyMessage ? <p>{invitationCopyMessage}</p> : null}
            </div>
          ) : null}
          {invitationsQuery.isPending ? (
            <p className="repository-state" role="status">
              Loading invitations…
            </p>
          ) : null}
          {invitationsQuery.error ? (
            <div className="repository-state-error" role="alert">
              <p>{asApiError(invitationsQuery.error).message}</p>
              <button
                className="repository-secondary-action"
                type="button"
                onClick={() => void invitationsQuery.refetch()}
              >
                Retry invitations
              </button>
            </div>
          ) : null}
          {invitationsQuery.data?.items.length === 0 && invitationOffset === 0 ? (
            <p className="repository-state">No pending organization invitations.</p>
          ) : null}
          {invitationsQuery.data?.items.length === 0 && invitationOffset > 0 ? (
            <p className="repository-state">
              No organization invitations are available on this page.
            </p>
          ) : null}
          {invitationsQuery.data ? (
            <>
              {invitationsQuery.data.items.length ? (
                <ul className="repository-list">
                  {invitationsQuery.data.items.map((invitation) => (
                    <li className="repository-list-item" key={invitation.id}>
                      <div className="repository-list-main">
                        <span className="repository-name-link">{invitation.target_email}</span>
                        <p>
                          {invitation.role} · expires{" "}
                          <time dateTime={invitation.expires_at}>
                            {new Date(invitation.expires_at).toLocaleDateString()}
                          </time>
                        </p>
                      </div>
                      {confirmingInvitationId === invitation.id ? (
                        <div className="organization-member-actions">
                          <span>Revoke this invitation?</span>
                          <button
                            className="repository-danger-action"
                            type="button"
                            disabled={revokeInvitationMutation.isPending}
                            onClick={() => revokeInvitationMutation.mutate(invitation.id)}
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
                          onClick={() => setConfirmingInvitationId(invitation.id)}
                        >
                          Revoke
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              ) : null}
              {invitationsQuery.data.total > invitationsQuery.data.limit || invitationOffset > 0 ? (
                <nav className="repository-pagination" aria-label="Organization invitation pages">
                  <button
                    className="repository-secondary-action"
                    type="button"
                    disabled={invitationOffset === 0 || invitationsQuery.isFetching}
                    onClick={() =>
                      setInvitationOffset((current) =>
                        Math.max(0, current - invitationsQuery.data.limit),
                      )
                    }
                  >
                    Previous
                  </button>
                  <p>
                    Showing {invitationOffset + 1}–
                    {invitationOffset + invitationsQuery.data.items.length} of{" "}
                    {invitationsQuery.data.total}
                  </p>
                  <button
                    className="repository-secondary-action"
                    type="button"
                    disabled={
                      invitationOffset + invitationsQuery.data.items.length >=
                        invitationsQuery.data.total || invitationsQuery.isFetching
                    }
                    onClick={() =>
                      setInvitationOffset((current) => current + invitationsQuery.data.limit)
                    }
                  >
                    Next
                  </button>
                </nav>
              ) : null}
            </>
          ) : null}
          {revokeInvitationMutation.error ? (
            <p className="repository-state-error" role="alert">
              {asApiError(revokeInvitationMutation.error).message}
            </p>
          ) : null}
        </section>
      ) : null}
      {organization.role === "owner" ? (
        <section className="repository-form-section" aria-labelledby="organization-transfer-title">
          <div className="repository-section-heading">
            <h2 id="organization-transfer-title">Transfer ownership</h2>
            <p>Ownership transfer requires the target user ID and your current password.</p>
          </div>
          <div className="organization-inline-form organization-transfer-form">
            <input
              aria-label="Target user ID"
              placeholder="Target user ID"
              value={transferUserId}
              onChange={(event) => setTransferUserId(event.currentTarget.value)}
            />
            <input
              aria-label="Current password"
              type="password"
              placeholder="Current password"
              value={transferPassword}
              onChange={(event) => setTransferPassword(event.currentTarget.value)}
            />
            <button
              className="repository-danger-action"
              type="button"
              disabled={!transferUserId.trim() || !transferPassword || transferMutation.isPending}
              onClick={() => transferMutation.mutate()}
            >
              {transferMutation.isPending ? "Transferring…" : "Transfer ownership"}
            </button>
          </div>
          {transferMutation.error ? (
            <p className="repository-state-error" role="alert">
              {asApiError(transferMutation.error).message}
            </p>
          ) : null}
        </section>
      ) : null}
      {organization.role !== "owner" ? (
        <section className="repository-danger-zone" aria-labelledby="organization-leave-title">
          <div>
            <h2 id="organization-leave-title">Leave organization</h2>
            <p>Leaving removes your membership. You may need an owner to add you again later.</p>
          </div>
          <button
            className="repository-danger-action"
            type="button"
            disabled={leaveMutation.isPending}
            onClick={() => setConfirmingLeave((current) => !current)}
          >
            {confirmingLeave ? "Cancel" : "Leave organization"}
          </button>
          {confirmingLeave ? (
            <button
              className="repository-danger-action"
              type="button"
              disabled={leaveMutation.isPending}
              onClick={leaveOrganizationFromCurrentSession}
            >
              {leaveMutation.isPending ? "Leaving…" : "Confirm leave"}
            </button>
          ) : null}
          {leaveMutation.error ? (
            <p className="repository-state-error" role="alert">
              {asApiError(leaveMutation.error).message}
            </p>
          ) : null}
        </section>
      ) : null}
    </main>
  );
}
