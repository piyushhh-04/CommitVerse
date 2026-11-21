import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import { listOrganizations } from "../api/organizations";
import { protectedQueryKey } from "../app/protectedQueryCache";
import { useAuth } from "../auth/AuthContext";
import { personalRepositoryListQueryOptions } from "../repositories/queries";

const DASHBOARD_REPOSITORY_LIMIT = 4;
const DASHBOARD_ORGANIZATION_LIMIT = 4;

function messageFor(error: unknown): string {
  return error instanceof ApiError ? error.message : "The Hub API could not be reached.";
}

function ErrorState({
  title,
  error,
  onRetry,
}: {
  title: string;
  error: unknown;
  onRetry: () => void;
}) {
  return (
    <div className="dashboard-error" role="alert">
      <h3>{title}</h3>
      <p>{messageFor(error)}</p>
      {error instanceof ApiError && error.requestId ? (
        <p className="repository-error-reference">Reference: {error.requestId}</p>
      ) : null}
      <button className="repository-secondary-action" type="button" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}

export function WorkspaceDashboardPage() {
  const auth = useAuth();
  const userId = auth.status === "authenticated" ? auth.user.id : "";
  const repositoriesQuery = useQuery({
    ...personalRepositoryListQueryOptions(userId, {
      limit: DASHBOARD_REPOSITORY_LIMIT,
      offset: 0,
    }),
    enabled: Boolean(userId),
  });
  const organizationsQuery = useQuery({
    queryKey: protectedQueryKey(userId, "organizations", "list"),
    queryFn: ({ signal }) => listOrganizations({ signal }),
    enabled: Boolean(userId),
  });

  if (!userId || auth.status !== "authenticated") return null;

  const repositories = repositoriesQuery.data;
  const organizations = organizationsQuery.data;

  return (
    <main className="repository-page workspace-dashboard">
      <header className="repository-page-header dashboard-welcome">
        <div>
          <h1 id="foundation-title" tabIndex={-1}>
            Welcome, {auth.user.display_name}
          </h1>
          <p className="repository-page-intro">
            Your repositories and shared spaces, ready when you are.
          </p>
        </div>
        <nav className="dashboard-actions" aria-label="Workspace actions">
          <Link className="repository-primary-action" to="/app/repositories/new">
            New repository
          </Link>
          <Link className="repository-secondary-action" to="/app/organizations/new">
            New organization
          </Link>
        </nav>
      </header>

      <div className="dashboard-summary-grid">
        <section className="dashboard-summary" aria-labelledby="dashboard-repositories-title">
          <div className="dashboard-summary-heading">
            <div>
              <h2 id="dashboard-repositories-title">Repositories</h2>
            </div>
            {repositories ? (
              <span className="dashboard-summary-count">{repositories.total} total</span>
            ) : null}
          </div>

          {repositoriesQuery.isPending ? (
            <p className="repository-state" role="status" aria-live="polite">
              Loading your repositories…
            </p>
          ) : null}
          {repositoriesQuery.isError && !repositories ? (
            <ErrorState
              title="Repositories unavailable"
              error={repositoriesQuery.error}
              onRetry={() => void repositoriesQuery.refetch()}
            />
          ) : null}
          {repositoriesQuery.isError && repositories ? (
            <p className="dashboard-inline-warning" role="status">
              The latest refresh failed. Showing the last loaded repositories.
              <button type="button" onClick={() => void repositoriesQuery.refetch()}>
                Retry
              </button>
            </p>
          ) : null}
          {repositories && repositories.items.length === 0 ? (
            <div className="dashboard-empty-state">
              <p>You have not created a repository yet.</p>
              <Link to="/app/repositories/new">Create your first repository</Link>
            </div>
          ) : null}
          {repositories && repositories.items.length > 0 ? (
            <>
              <ul className="repository-list dashboard-list">
                {repositories.items.map((repository) => (
                  <li className="repository-list-item" key={repository.id}>
                    <div className="repository-list-main">
                      <Link
                        className="repository-name-link"
                        to={`/app/repositories/${repository.id}`}
                      >
                        {repository.name}
                      </Link>
                      <p>{repository.description || "No description provided."}</p>
                    </div>
                    <span className={`repository-visibility-tag is-${repository.visibility}`}>
                      {repository.visibility}
                    </span>
                  </li>
                ))}
              </ul>
              <Link className="dashboard-view-all" to="/app/repositories">
                View all repositories <span aria-hidden="true">→</span>
              </Link>
            </>
          ) : null}
        </section>

        <section className="dashboard-summary" aria-labelledby="dashboard-organizations-title">
          <div className="dashboard-summary-heading">
            <div>
              <h2 id="dashboard-organizations-title">Organizations</h2>
            </div>
            {organizations ? (
              <span className="dashboard-summary-count">{organizations.total} total</span>
            ) : null}
          </div>

          {organizationsQuery.isPending ? (
            <p className="repository-state" role="status" aria-live="polite">
              Loading your organizations…
            </p>
          ) : null}
          {organizationsQuery.isError && !organizations ? (
            <ErrorState
              title="Organizations unavailable"
              error={organizationsQuery.error}
              onRetry={() => void organizationsQuery.refetch()}
            />
          ) : null}
          {organizationsQuery.isError && organizations ? (
            <p className="dashboard-inline-warning" role="status">
              The latest refresh failed. Showing the last loaded organizations.
              <button type="button" onClick={() => void organizationsQuery.refetch()}>
                Retry
              </button>
            </p>
          ) : null}
          {organizations && organizations.items.length === 0 ? (
            <div className="dashboard-empty-state">
              <p>You are not part of an organization yet.</p>
              <div>
                <Link to="/app/organizations/new">Create an organization</Link>
                <Link to="/app/invitations/accept">Accept an invitation</Link>
              </div>
            </div>
          ) : null}
          {organizations && organizations.items.length > 0 ? (
            <>
              <ul className="repository-list dashboard-list">
                {organizations.items.slice(0, DASHBOARD_ORGANIZATION_LIMIT).map((organization) => (
                  <li className="repository-list-item" key={organization.id}>
                    <div className="repository-list-main">
                      <Link
                        className="repository-name-link"
                        to={`/app/organizations/${organization.id}`}
                      >
                        {organization.name}
                      </Link>
                      <p>
                        {organization.slug} · {organization.role ?? "member"}
                      </p>
                    </div>
                    <span className="repository-visibility-tag">{organization.state}</span>
                  </li>
                ))}
              </ul>
              <Link className="dashboard-view-all" to="/app/organizations">
                View all organizations <span aria-hidden="true">→</span>
              </Link>
            </>
          ) : null}
        </section>
      </div>
    </main>
  );
}
