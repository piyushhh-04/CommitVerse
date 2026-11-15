import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { RepositoryForm, type RepositoryFormValues } from "../components/RepositoryForm";
import { RepositoryBrowsePanel } from "../components/RepositoryBrowsePanel";
import { useAuth } from "../auth/AuthContext";
import {
  personalRepositoryDetailQueryOptions,
  personalRepositoryMutationClient,
  personalRepositoryMutationOptions,
} from "../repositories/queries";

function formatRepositoryDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function repositoryUnavailableMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 404) {
    return "This repository is unavailable. It may have been deleted or you may not have access.";
  }
  return error instanceof Error ? error.message : "Repository details could not be loaded.";
}

export function RepositoryDetailPage() {
  const { repositoryId = "" } = useParams();
  const location = useLocation();
  const auth = useAuth();
  const userId = auth.status === "authenticated" ? auth.user.id : "";
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const deleteTriggerRef = useRef<HTMLButtonElement>(null);
  const deleteCancelRef = useRef<HTMLButtonElement>(null);
  const mutations = personalRepositoryMutationOptions(queryClient, userId);
  const repositoryQuery = useQuery({
    ...personalRepositoryDetailQueryOptions(userId, repositoryId),
    enabled: Boolean(userId && repositoryId),
  });
  const mutationClient = personalRepositoryMutationClient(queryClient);
  const updateMutation = useMutation(mutations.update, mutationClient);
  const deleteMutation = useMutation(mutations.delete, mutationClient);
  const repository = repositoryQuery.data;
  const focusDestinationHeading =
    typeof location.state === "object" &&
    location.state !== null &&
    "focusDestinationHeading" in location.state &&
    location.state.focusDestinationHeading === true;

  useEffect(() => {
    if (!focusDestinationHeading || repositoryQuery.isPending) return;
    const heading = document.getElementById("foundation-title");
    if (heading && document.activeElement !== heading) heading.focus();
  }, [focusDestinationHeading, repositoryId, repositoryQuery.isPending]);

  useEffect(() => {
    if (confirmingDelete) deleteCancelRef.current?.focus();
  }, [confirmingDelete]);

  useEffect(() => {
    if (!confirmingDelete || deleteMutation.isPending) return;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setConfirmingDelete(false);
        deleteTriggerRef.current?.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [confirmingDelete, deleteMutation.isPending]);

  if (!userId) return null;

  function handleUpdate(values: RepositoryFormValues) {
    if (!repository) return;
    const changes: {
      name?: string;
      description?: string | null;
      visibility?: RepositoryFormValues["visibility"];
    } = {};
    if (values.name !== repository.name) changes.name = values.name;
    const description = values.description || null;
    if (description !== repository.description) changes.description = description;
    if (values.visibility !== repository.visibility) changes.visibility = values.visibility;
    if (Object.keys(changes).length === 0) {
      updateMutation.reset();
      return;
    }
    updateMutation.mutate({ repositoryId, changes });
  }

  function handleDelete() {
    deleteMutation.mutate(repositoryId, {
      onSuccess: () => {
        void navigate("/app/repositories", {
          state: { focusDestinationHeading: true },
        });
      },
    });
  }

  if (!repository && repositoryQuery.isPending) {
    return (
      <main className="repository-page">
        <p className="eyebrow">Personal repositories / Details</p>
        <h1 id="foundation-title" aria-busy="true" tabIndex={-1}>
          Repository details
        </h1>
        <p className="repository-state" role="status" aria-live="polite">
          Loading repository…
        </p>
      </main>
    );
  }

  if (!repository && (repositoryQuery.isError || !repositoryId)) {
    return (
      <main className="repository-page repository-state-page">
        <p className="eyebrow">Personal repositories / Details</p>
        <h1 id="foundation-title" tabIndex={-1}>
          Repository unavailable
        </h1>
        <p className="repository-state-error" role="alert">
          {repositoryUnavailableMessage(repositoryQuery.error)}
        </p>
        {repositoryQuery.isError && repositoryQuery.error instanceof ApiError ? (
          repositoryQuery.error.requestId ? (
            <p className="repository-error-reference">
              Reference: {repositoryQuery.error.requestId}
            </p>
          ) : null
        ) : null}
        <Link className="repository-secondary-action" to="/app/repositories">
          Back to repositories
        </Link>
        {repositoryId &&
        repositoryQuery.isError &&
        !(repositoryQuery.error instanceof ApiError && repositoryQuery.error.status === 404) ? (
          <button
            className="repository-secondary-action"
            type="button"
            onClick={() => void repositoryQuery.refetch()}
          >
            Try again
          </button>
        ) : null}
      </main>
    );
  }

  if (!repository) return null;

  return (
    <main className="repository-page repository-detail-page">
      <Link className="repository-back-link" to="/app/repositories">
        <span aria-hidden="true">←</span> All repositories
      </Link>

      {repositoryQuery.isError ? (
        <div className="repository-inline-warning" role="alert">
          <span>
            {repositoryUnavailableMessage(repositoryQuery.error)} Showing the last loaded details.
          </span>
          <button type="button" onClick={() => void repositoryQuery.refetch()}>
            Retry
          </button>
        </div>
      ) : null}

      <header className="repository-detail-header">
        <div>
          <p className="eyebrow">Personal repository / Details</p>
          <h1 id="foundation-title" tabIndex={-1}>
            {repository.name}
          </h1>
          <p className="repository-detail-description">
            {repository.description || "No description provided."}
          </p>
        </div>
        <span className={`repository-visibility-tag is-${repository.visibility}`}>
          {repository.visibility}
        </span>
      </header>

      <section className="repository-metadata" aria-label="Repository metadata">
        <div>
          <span>Created</span>
          <time dateTime={repository.created_at}>
            {formatRepositoryDate(repository.created_at)}
          </time>
        </div>
        <div>
          <span>Last updated</span>
          <time dateTime={repository.updated_at}>
            {formatRepositoryDate(repository.updated_at)}
          </time>
        </div>
      </section>

      <p className="repository-visibility-note">
        Public visibility applies to repository metadata only. Anonymous repository access is not
        available.
      </p>

      <RepositoryBrowsePanel repositoryId={repository.id} />

      <section className="repository-form-section" aria-labelledby="repository-settings-title">
        <div className="repository-section-heading">
          <p className="eyebrow">Settings</p>
          <h2 id="repository-settings-title">Repository details</h2>
          <p>Update the name, description, or visibility for this repository.</p>
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
          error={updateMutation.error ?? null}
          successMessage={updateMutation.isSuccess ? "Changes saved." : null}
          onValuesChange={() => updateMutation.reset()}
          onSubmit={handleUpdate}
        />
      </section>

      <section className="repository-danger-zone" aria-labelledby="repository-delete-title">
        <div>
          <p className="eyebrow">Destructive action</p>
          <h2 id="repository-delete-title">Delete this repository</h2>
          <p>
            Deletion permanently removes this repository’s local Core storage and leaves a metadata
            record. This cannot be undone.
          </p>
        </div>
        <button
          ref={deleteTriggerRef}
          className="repository-danger-action"
          type="button"
          disabled={deleteMutation.isPending}
          onClick={() => {
            deleteMutation.reset();
            setConfirmingDelete(true);
          }}
        >
          Delete repository
        </button>

        {confirmingDelete ? (
          <section
            className="repository-delete-confirmation"
            aria-labelledby="delete-confirmation-title"
          >
            <h3 id="delete-confirmation-title">Delete {repository.name}?</h3>
            <p>
              The repository and its stored contents will be removed. If cleanup fails, this page
              will keep the repository ID available for a retry; reloading may make a pending
              deletion unavailable here.
            </p>
            {deleteMutation.error ? (
              <div className="repository-form-error" role="alert">
                <p>{deleteMutation.error.message}</p>
                {deleteMutation.error.requestId ? (
                  <p className="repository-error-reference">
                    Reference: {deleteMutation.error.requestId}
                  </p>
                ) : null}
                {deleteMutation.error.status === 503 ? (
                  <p>The deletion may still be pending. Retry here before leaving this page.</p>
                ) : null}
              </div>
            ) : null}
            <div className="repository-confirmation-actions">
              <button
                ref={deleteCancelRef}
                className="repository-secondary-action"
                type="button"
                disabled={deleteMutation.isPending}
                onClick={() => {
                  setConfirmingDelete(false);
                  deleteTriggerRef.current?.focus();
                }}
              >
                Cancel
              </button>
              <button
                className="repository-danger-action"
                type="button"
                disabled={deleteMutation.isPending}
                aria-busy={deleteMutation.isPending}
                onClick={handleDelete}
              >
                {deleteMutation.isPending
                  ? "Deleting…"
                  : deleteMutation.isError
                    ? "Retry deletion"
                    : "Confirm deletion"}
              </button>
            </div>
          </section>
        ) : null}
      </section>
    </main>
  );
}

export function RepositoryDetailRoute() {
  const { repositoryId = "" } = useParams();
  return <RepositoryDetailPage key={repositoryId} />;
}
