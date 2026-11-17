import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  getProtectedQueryIdentityGeneration,
  isProtectedQueryIdentity,
  protectedQueryKey,
} from "../app/protectedQueryCache";
import {
  deleteOrganizationRepository,
  getOrganizationRepository,
  updateOrganizationRepository,
} from "../api/organizationRepositories";
import { useAuth } from "../auth/AuthContext";
import { RepositoryForm, type RepositoryFormValues } from "../components/RepositoryForm";
import { RepositoryBrowsePanel } from "../components/RepositoryBrowsePanel";
import { RepositoryAccessPanel } from "../components/RepositoryAccessPanel";

function operationError(error: unknown): ApiError {
  return error instanceof ApiError
    ? error
    : new ApiError("The organization repository operation failed.", {
        status: null,
        code: "unexpected_error",
        requestId: null,
        cause: error,
      });
}

export function OrganizationRepositoryDetailPage() {
  const { organizationId = "", repositoryId = "" } = useParams();
  const auth = useAuth();
  const userId = auth.status === "authenticated" ? auth.user.id : "";
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const deleteButtonRef = useRef<HTMLButtonElement>(null);
  const repositoryQuery = useQuery({
    queryKey: protectedQueryKey(
      userId,
      "organization-repositories",
      organizationId,
      "detail",
      repositoryId,
    ),
    queryFn: ({ signal }) => getOrganizationRepository(organizationId, repositoryId, { signal }),
    enabled: Boolean(userId && organizationId && repositoryId),
  });
  const updateMutation = useMutation({
    mutationKey: protectedQueryKey(
      userId,
      "organization-repositories",
      organizationId,
      "mutation",
      "update",
    ),
    mutationFn: (values: RepositoryFormValues) =>
      updateOrganizationRepository(organizationId, repositoryId, {
        name: values.name,
        description: values.description || null,
        visibility: values.visibility,
      }),
    retry: false,
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: protectedQueryKey(userId, "organization-repositories", organizationId),
      });
    },
  });
  const deleteMutation = useMutation<void, ApiError, number>({
    mutationKey: protectedQueryKey(
      userId,
      "organization-repositories",
      organizationId,
      "mutation",
      "delete",
    ),
    mutationFn: () => deleteOrganizationRepository(organizationId, repositoryId),
    retry: false,
    onSuccess: async (_result, identityGeneration) => {
      if (!isProtectedQueryIdentity(queryClient, userId, identityGeneration)) return;
      await queryClient.invalidateQueries({
        queryKey: protectedQueryKey(userId, "organization-repositories", organizationId),
      });
      if (!isProtectedQueryIdentity(queryClient, userId, identityGeneration)) return;
      void navigate(`/app/organizations/${organizationId}/repositories`, {
        state: { focusDestinationHeading: true },
      });
    },
  });
  function deleteRepositoryFromCurrentSession() {
    const identityGeneration = getProtectedQueryIdentityGeneration(queryClient, userId);
    if (identityGeneration !== null) deleteMutation.mutate(identityGeneration);
  }
  useEffect(() => {
    if (
      location.state &&
      typeof location.state === "object" &&
      "focusDestinationHeading" in location.state &&
      !repositoryQuery.isPending
    ) {
      document.getElementById("foundation-title")?.focus();
    }
  }, [location.state, repositoryQuery.isPending]);
  if (!userId) return null;
  if (repositoryQuery.isPending)
    return (
      <main className="repository-page">
        <p className="eyebrow">Organization repositories / Details</p>
        <h1 id="foundation-title" tabIndex={-1}>
          Repository details
        </h1>
        <p className="repository-state" role="status">
          Loading repository…
        </p>
      </main>
    );
  const repository = repositoryQuery.data;
  if (!repository || repositoryQuery.isError)
    return (
      <main className="repository-page">
        <p className="eyebrow">Organization repositories / Details</p>
        <h1 id="foundation-title" tabIndex={-1}>
          Repository unavailable
        </h1>
        <p className="repository-state-error" role="alert">
          {operationError(repositoryQuery.error).message}
        </p>
        <Link
          className="repository-secondary-action"
          to={`/app/organizations/${organizationId}/repositories`}
        >
          Back to repositories
        </Link>
      </main>
    );
  return (
    <main className="repository-page repository-form-page">
      <Link
        className="repository-back-link"
        to={`/app/organizations/${organizationId}/repositories`}
      >
        <span aria-hidden="true">←</span> Organization repositories
      </Link>
      <header className="repository-page-header repository-form-header">
        <div>
          <p className="eyebrow">Organization repositories / Details</p>
          <h1 id="foundation-title" tabIndex={-1}>
            {repository.name}
          </h1>
          <p className="repository-page-intro">
            Metadata and lifecycle settings for this organization-owned Core repository.
          </p>
        </div>
      </header>
      <RepositoryBrowsePanel repositoryId={repository.id} userId={userId} />
      <RepositoryAccessPanel repositoryId={repository.id} userId={userId} />
      <section
        className="repository-form-section"
        aria-labelledby="organization-repository-settings-title"
      >
        <div className="repository-section-heading">
          <p className="eyebrow">Settings</p>
          <h2 id="organization-repository-settings-title">Repository details</h2>
        </div>
        <RepositoryForm
          key={`${repository.id}-${repository.updated_at}`}
          initialValues={{
            name: repository.name,
            description: repository.description ?? "",
            visibility: repository.visibility,
          }}
          pending={updateMutation.isPending}
          submitLabel="Save changes"
          pendingLabel="Saving changes…"
          error={updateMutation.error instanceof ApiError ? updateMutation.error : null}
          successMessage={updateMutation.isSuccess ? "Changes saved." : null}
          onValuesChange={() => updateMutation.reset()}
          onSubmit={(values) => updateMutation.mutate(values)}
        />
      </section>
      <section
        className="repository-danger-zone"
        aria-labelledby="organization-repository-delete-title"
      >
        <div>
          <p className="eyebrow">Destructive action</p>
          <h2 id="organization-repository-delete-title">Delete this repository</h2>
          <p>Deletion removes the Core storage and leaves a metadata tombstone.</p>
        </div>
        <button
          ref={deleteButtonRef}
          className="repository-danger-action"
          type="button"
          disabled={deleteMutation.isPending}
          onClick={() => setConfirmingDelete(true)}
        >
          Delete repository
        </button>
        {confirmingDelete ? (
          <div className="repository-delete-confirmation">
            <p>
              Delete <strong>{repository.name}</strong>? This cannot be undone.
            </p>
            <button
              className="repository-danger-action"
              type="button"
              disabled={deleteMutation.isPending}
              onClick={deleteRepositoryFromCurrentSession}
            >
              {deleteMutation.isPending ? "Deleting…" : "Confirm deletion"}
            </button>
            <button
              className="repository-secondary-action"
              type="button"
              disabled={deleteMutation.isPending}
              onClick={() => {
                setConfirmingDelete(false);
                deleteButtonRef.current?.focus();
              }}
            >
              Cancel
            </button>
            {deleteMutation.error ? (
              <p className="repository-state-error" role="alert">
                {operationError(deleteMutation.error).message}
              </p>
            ) : null}
          </div>
        ) : null}
      </section>
    </main>
  );
}
