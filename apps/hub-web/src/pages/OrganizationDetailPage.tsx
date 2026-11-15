import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
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
  const [invitationEmail, setInvitationEmail] = useState("");
  const [invitationRole, setInvitationRole] = useState<MembershipRole>("member");
  const [latestInvitationToken, setLatestInvitationToken] = useState<string | null>(null);
  const [transferUserId, setTransferUserId] = useState("");
  const [transferPassword, setTransferPassword] = useState("");
  const organizationQuery = useQuery({
    queryKey: ["organizations", userId, "detail", organizationId],
    queryFn: ({ signal }) => getOrganization(organizationId, { signal }),
    enabled: Boolean(userId && organizationId),
  });
  const canManage =
    organizationQuery.data?.role === "owner" || organizationQuery.data?.role === "admin";
  const membersQuery = useQuery({
    queryKey: ["organizations", organizationId, "members"],
    queryFn: ({ signal }) => listOrganizationMembers(organizationId, { signal }),
    enabled: Boolean(userId && organizationId),
  });
  const invitationsQuery = useQuery({
    queryKey: ["organizations", organizationId, "invitations"],
    queryFn: ({ signal }) => listOrganizationInvitations(organizationId, { signal }),
    enabled: Boolean(userId && organizationId && canManage),
  });
  const userSearchQuery = useQuery({
    queryKey: ["users", "search", memberUserId.trim()],
    queryFn: ({ signal }) => searchUsers(memberUserId.trim(), { signal }),
    enabled: Boolean(canManage && memberUserId.trim().length >= 2),
  });
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["organizations"] }),
      queryClient.invalidateQueries({ queryKey: ["organizations", organizationId, "members"] }),
      queryClient.invalidateQueries({ queryKey: ["organizations", organizationId, "invitations"] }),
    ]);
  };
  const updateMutation = useMutation<Organization, ApiError, OrganizationFormValues>({
    mutationFn: (values) => updateOrganization(organizationId, values),
    retry: false,
    onSuccess: invalidate,
  });
  const addMutation = useMutation({
    mutationFn: () => addOrganizationMember(organizationId, memberUserId.trim(), memberRole),
    retry: false,
    onSuccess: async () => {
      setMemberUserId("");
      await invalidate();
    },
  });
  const invitationMutation = useMutation({
    mutationFn: () =>
      createOrganizationInvitation(organizationId, invitationEmail.trim(), invitationRole),
    retry: false,
    onSuccess: async (invitation) => {
      setInvitationEmail("");
      setLatestInvitationToken(invitation.token);
      await invalidate();
    },
  });
  const revokeInvitationMutation = useMutation({
    mutationFn: (invitationId: string) =>
      revokeOrganizationInvitation(organizationId, invitationId),
    retry: false,
    onSuccess: invalidate,
  });
  const roleMutation = useMutation({
    mutationFn: ({ id, role }: { id: string; role: MembershipRole }) =>
      changeOrganizationMemberRole(organizationId, id, role),
    retry: false,
    onSuccess: invalidate,
  });
  const removeMutation = useMutation({
    mutationFn: (id: string) => removeOrganizationMember(organizationId, id),
    retry: false,
    onSuccess: invalidate,
  });
  const leaveMutation = useMutation({
    mutationFn: () => leaveOrganization(organizationId),
    retry: false,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["organizations"] });
      void navigate("/app/organizations", { state: { focusDestinationHeading: true } });
    },
  });
  const transferMutation = useMutation({
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
        <p className="eyebrow">Organizations / Details</p>
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
        <p className="eyebrow">Organizations / Details</p>
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
          <p className="eyebrow">Organizations / {organization.role}</p>
          <h1 id="foundation-title" tabIndex={-1}>
            {organization.name}
          </h1>
          <p className="repository-page-intro">
            {organization.slug} · {organization.state}
          </p>
        </div>
      </header>
      <p className="organization-repository-link-row">
        <Link
          className="repository-secondary-action"
          to={`/app/organizations/${organizationId}/repositories`}
        >
          View organization repositories
        </Link>
      </p>
      <section className="repository-form-section" aria-labelledby="organization-settings-title">
        <div className="repository-section-heading">
          <p className="eyebrow">Settings</p>
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
          <p className="eyebrow">Membership</p>
          <h2 id="organization-members-title">Members</h2>
          <p>
            Membership changes are explicit; membership does not automatically grant repository
            access.
          </p>
        </div>
        {membersQuery.isPending ? (
          <p className="repository-state" role="status">
            Loading members…
          </p>
        ) : null}
        {membersQuery.isError ? (
          <p className="repository-state-error" role="alert">
            {asApiError(membersQuery.error).message}
          </p>
        ) : null}
        {membersQuery.data ? (
          <ul className="repository-list">
            {membersQuery.data.items.map((member) => (
              <li className="repository-list-item" key={member.user_id}>
                <div className="repository-list-main">
                  <span className="repository-name-link">{member.user_id}</span>
                  <p>Joined {new Date(member.joined_at).toLocaleDateString()}</p>
                </div>
                <div className="organization-member-actions">
                  <span className="repository-visibility-tag">{member.role}</span>
                  {canManage && member.user_id !== userId && member.role !== "owner" ? (
                    <>
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
                      <button
                        className="repository-danger-action"
                        type="button"
                        onClick={() => removeMutation.mutate(member.user_id)}
                      >
                        Remove
                      </button>
                    </>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        ) : null}
      </section>
      {canManage ? (
        <section
          className="repository-form-section"
          aria-labelledby="organization-add-member-title"
        >
          <div className="repository-section-heading">
            <p className="eyebrow">Owner/admin action</p>
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
              <option value="admin">Admin</option>
            </select>
            <button
              className="repository-primary-action"
              type="button"
              disabled={!memberUserId.trim() || addMutation.isPending}
              onClick={() => addMutation.mutate()}
            >
              {addMutation.isPending ? "Adding…" : "Add member"}
            </button>
          </div>
          {userSearchQuery.isPending ? (
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
        </section>
      ) : null}
      {canManage ? (
        <section
          className="repository-form-section"
          aria-labelledby="organization-invitations-title"
        >
          <div className="repository-section-heading">
            <p className="eyebrow">Owner/admin action</p>
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
                onClick={() => void navigator.clipboard?.writeText(latestInvitationToken)}
              >
                Copy token
              </button>
            </div>
          ) : null}
          {invitationsQuery.isPending ? (
            <p className="repository-state" role="status">
              Loading invitations…
            </p>
          ) : null}
          {invitationsQuery.error ? (
            <p className="repository-state-error" role="alert">
              {asApiError(invitationsQuery.error).message}
            </p>
          ) : null}
          {invitationsQuery.data?.items.length ? (
            <ul className="repository-list">
              {invitationsQuery.data.items.map((invitation) => (
                <li className="repository-list-item" key={invitation.id}>
                  <div className="repository-list-main">
                    <span className="repository-name-link">{invitation.target_email}</span>
                    <p>
                      {invitation.role} · expires{" "}
                      {new Date(invitation.expires_at).toLocaleDateString()}
                    </p>
                  </div>
                  <button
                    className="repository-danger-action"
                    type="button"
                    disabled={revokeInvitationMutation.isPending}
                    onClick={() => revokeInvitationMutation.mutate(invitation.id)}
                  >
                    Revoke
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}
      {organization.role === "owner" ? (
        <section className="repository-form-section" aria-labelledby="organization-transfer-title">
          <div className="repository-section-heading">
            <p className="eyebrow">Owner action</p>
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
            <p className="eyebrow">Membership action</p>
            <h2 id="organization-leave-title">Leave organization</h2>
            <p>Leaving removes your membership. You may need an owner to add you again later.</p>
          </div>
          <button
            className="repository-danger-action"
            type="button"
            disabled={leaveMutation.isPending}
            onClick={() => leaveMutation.mutate()}
          >
            {leaveMutation.isPending ? "Leaving…" : "Leave organization"}
          </button>
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
