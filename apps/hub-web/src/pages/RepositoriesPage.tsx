import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import { personalRepositoryListQueryOptions } from "../repositories/queries";
import { useAuth } from "../auth/AuthContext";

const REPOSITORIES_PAGE_SIZE = 50;

function formatRepositoryDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
}

function RepositoryListError({ error, onRetry }: { error: ApiError; onRetry: () => void }) {
  return (
    <section className="repository-state repository-state-error" role="alert">
      <p className="eyebrow">Repositories / Unavailable</p>
      <h2>We could not load your repositories.</h2>
      <p>{error.message}</p>
      {error.requestId ? (
        <p className="repository-error-reference">Reference: {error.requestId}</p>
      ) : null}
      <button className="repository-secondary-action" type="button" onClick={onRetry}>
        Try again
      </button>
    </section>
  );
}

export function RepositoriesPage() {
  const auth = useAuth();
  const userId = auth.status === "authenticated" ? auth.user.id : "";
  const [offset, setOffset] = useState(0);
  const repositoriesQuery = useQuery({
    ...personalRepositoryListQueryOptions(userId, { limit: REPOSITORIES_PAGE_SIZE, offset }),
    enabled: Boolean(userId),
  });
  const list = repositoriesQuery.data;

  if (!userId) return null;

  return (
    <main className="repository-page">
      <header className="repository-page-header">
        <div>
          <p className="eyebrow">CommitVerse Hub / Personal repositories</p>
          <h1 id="foundation-title" tabIndex={-1}>
            Repositories
          </h1>
          <p className="repository-page-intro">
            A considered home for the repositories you manage.
          </p>
        </div>
        <Link
          className="repository-primary-action repository-create-link"
          to="/app/repositories/new"
        >
          New repository <span aria-hidden="true">↗</span>
        </Link>
      </header>

      <aside className="repository-visibility-note">
        <span className="repository-note-marker" aria-hidden="true">
          i
        </span>
        <p>
          Public visibility applies to repository metadata only. Anonymous repository access is not
          available.
        </p>
      </aside>

      {repositoriesQuery.isPending ? (
        <p className="repository-state" role="status" aria-live="polite">
          Loading repositories…
        </p>
      ) : null}

      {repositoriesQuery.isError && !list ? (
        <RepositoryListError
          error={
            repositoriesQuery.error instanceof ApiError
              ? repositoriesQuery.error
              : new ApiError("The repository list could not be loaded.", {
                  status: null,
                  code: "unexpected_error",
                  requestId: null,
                  cause: repositoriesQuery.error,
                })
          }
          onRetry={() => void repositoriesQuery.refetch()}
        />
      ) : null}

      {list && list.items.length === 0 && list.total === 0 && offset === 0 ? (
        <section
          className="repository-state repository-empty-state"
          aria-labelledby="repository-empty-title"
        >
          <p className="eyebrow">A clear beginning</p>
          <h2 id="repository-empty-title">Your repositories will live here.</h2>
          <p>
            Create a personal repository to start organizing your work. Hub currently manages
            repository metadata; repository contents are not browsable here.
          </p>
          <Link className="repository-secondary-action" to="/app/repositories/new">
            Create your first repository
          </Link>
        </section>
      ) : null}

      {list && list.items.length === 0 && offset > 0 ? (
        <section className="repository-state repository-empty-state">
          <p className="eyebrow">Page no longer available</p>
          <h2>No repositories on this page.</h2>
          <p>The list may have changed since you moved to this page.</p>
          <button
            className="repository-secondary-action"
            type="button"
            onClick={() => setOffset(0)}
          >
            Back to the first page
          </button>
        </section>
      ) : null}

      {list && list.items.length > 0 ? (
        <section className="repository-list-section" aria-labelledby="repository-list-title">
          <div className="repository-list-heading">
            <h2 id="repository-list-title">Your repositories</h2>
            <p>
              {list.total} {list.total === 1 ? "repository" : "repositories"}
            </p>
          </div>
          <ul className="repository-list">
            {list.items.map((repository) => (
              <li className="repository-list-item" key={repository.id}>
                <div className="repository-list-main">
                  <Link
                    className="repository-name-link"
                    to={`/app/repositories/${repository.id}`}
                    aria-label={`View repository ${repository.name}`}
                  >
                    {repository.name}
                  </Link>
                  <p>{repository.description || "No description provided."}</p>
                </div>
                <div className="repository-list-meta">
                  <span className={`repository-visibility-tag is-${repository.visibility}`}>
                    {repository.visibility}
                  </span>
                  <span>
                    Updated{" "}
                    <time dateTime={repository.updated_at}>
                      {formatRepositoryDate(repository.updated_at)}
                    </time>
                  </span>
                </div>
              </li>
            ))}
          </ul>
          {repositoriesQuery.isError ? (
            <p className="repository-inline-warning" role="status">
              The latest refresh failed. The repositories shown may be out of date.
              <button type="button" onClick={() => void repositoriesQuery.refetch()}>
                Retry
              </button>
            </p>
          ) : null}
          <nav className="repository-pagination" aria-label="Repository pages">
            <button
              className="repository-secondary-action"
              type="button"
              disabled={offset === 0 || repositoriesQuery.isFetching}
              onClick={() => setOffset((current) => Math.max(0, current - REPOSITORIES_PAGE_SIZE))}
            >
              Previous
            </button>
            <p aria-live="polite">
              Showing {offset + 1}–{offset + list.items.length} of {list.total}
            </p>
            <button
              className="repository-secondary-action"
              type="button"
              disabled={offset + list.items.length >= list.total || repositoriesQuery.isFetching}
              onClick={() => setOffset((current) => current + REPOSITORIES_PAGE_SIZE)}
            >
              Next
            </button>
          </nav>
        </section>
      ) : null}
    </main>
  );
}
