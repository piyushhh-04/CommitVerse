import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { protectedQueryKey } from "../app/protectedQueryCache";
import { listOrganizationRepositories } from "../api/organizationRepositories";
import { useAuth } from "../auth/AuthContext";

export function OrganizationRepositoriesPage() {
  const { organizationId = "" } = useParams();
  const auth = useAuth();
  const userId = auth.status === "authenticated" ? auth.user.id : "";
  const [offset, setOffset] = useState(0);
  const repositoriesQuery = useQuery({
    queryKey: protectedQueryKey(userId, "organization-repositories", organizationId, offset),
    queryFn: ({ signal }) => listOrganizationRepositories(organizationId, 50, offset, { signal }),
    enabled: Boolean(userId && organizationId),
  });
  const list = repositoriesQuery.data;
  if (!userId) return null;
  return (
    <main className="repository-page">
      <Link className="repository-back-link" to={`/app/organizations/${organizationId}`}>
        <span aria-hidden="true">←</span> Organization
      </Link>
      <header className="repository-page-header">
        <div>
          <h1 id="foundation-title" tabIndex={-1}>
            Repositories
          </h1>
          <p className="repository-page-intro">
            Core-backed repositories managed by this organization.
          </p>
        </div>
        <Link
          className="repository-primary-action"
          to={`/app/organizations/${organizationId}/repositories/new`}
        >
          New repository <span aria-hidden="true">↗</span>
        </Link>
      </header>
      {repositoriesQuery.isPending ? (
        <p className="repository-state" role="status">
          Loading repositories…
        </p>
      ) : null}
      {repositoriesQuery.isError ? (
        <section className="repository-state repository-state-error" role="alert">
          <h2>We could not load these repositories.</h2>
          <p>
            {repositoriesQuery.error instanceof ApiError
              ? repositoriesQuery.error.message
              : "Try again later."}
          </p>
          <button
            className="repository-secondary-action"
            type="button"
            onClick={() => void repositoriesQuery.refetch()}
          >
            Try again
          </button>
        </section>
      ) : null}
      {list && list.items.length === 0 && offset === 0 ? (
        <section className="repository-state repository-empty-state">
          <h2>No organization repositories yet.</h2>
          <p>Create the first repository for this organization.</p>
          <Link
            className="repository-secondary-action"
            to={`/app/organizations/${organizationId}/repositories/new`}
          >
            Create repository
          </Link>
        </section>
      ) : null}
      {list && list.items.length > 0 ? (
        <section
          className="repository-list-section"
          aria-labelledby="organization-repository-list-title"
        >
          <div className="repository-list-heading">
            <h2 id="organization-repository-list-title">Organization repositories</h2>
            <p>{list.total} total</p>
          </div>
          <ul className="repository-list">
            {list.items.map((repository) => (
              <li className="repository-list-item" key={repository.id}>
                <div className="repository-list-main">
                  <Link
                    className="repository-name-link"
                    to={`/app/organizations/${organizationId}/repositories/${repository.id}`}
                  >
                    {repository.name}
                  </Link>
                  <p>{repository.description || "No description provided."}</p>
                </div>
                <div className="repository-list-meta">
                  <span className={`repository-visibility-tag is-${repository.visibility}`}>
                    {repository.visibility}
                  </span>
                </div>
              </li>
            ))}
          </ul>
          <nav className="repository-pagination" aria-label="Organization repository pages">
            <button
              className="repository-secondary-action"
              type="button"
              disabled={offset === 0 || repositoriesQuery.isFetching}
              onClick={() => setOffset((current) => Math.max(0, current - 50))}
            >
              Previous
            </button>
            <p>
              Showing {offset + 1}–{offset + list.items.length} of {list.total}
            </p>
            <button
              className="repository-secondary-action"
              type="button"
              disabled={offset + list.items.length >= list.total || repositoriesQuery.isFetching}
              onClick={() => setOffset((current) => current + 50)}
            >
              Next
            </button>
          </nav>
        </section>
      ) : null}
    </main>
  );
}
