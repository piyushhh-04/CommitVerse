import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { listOrganizations } from "../api/organizations";

export function OrganizationsPage() {
  const auth = useAuth();
  const userId = auth.status === "authenticated" ? auth.user.id : "";
  const organizationsQuery = useQuery({
    queryKey: ["organizations", userId, "list"],
    queryFn: ({ signal }) => listOrganizations({ signal }),
    enabled: Boolean(userId),
  });
  const list = organizationsQuery.data;

  if (!userId) return null;
  return (
    <main className="repository-page">
      <header className="repository-page-header">
        <div>
          <p className="eyebrow">CommitVerse Hub / Organizations</p>
          <h1 id="foundation-title" tabIndex={-1}>
            Organizations
          </h1>
          <p className="repository-page-intro">
            Shared spaces for teams, permissions, and repository collaboration.
          </p>
        </div>
        <Link className="repository-primary-action" to="/app/organizations/new">
          New organization <span aria-hidden="true">↗</span>
        </Link>
      </header>
      {organizationsQuery.isPending ? (
        <p className="repository-state" role="status">
          Loading organizations…
        </p>
      ) : null}
      {organizationsQuery.isError ? (
        <section className="repository-state repository-state-error" role="alert">
          <p className="eyebrow">Organizations / Unavailable</p>
          <h2>We could not load your organizations.</h2>
          <p>
            {organizationsQuery.error instanceof ApiError
              ? organizationsQuery.error.message
              : "Try again later."}
          </p>
          <button
            className="repository-secondary-action"
            type="button"
            onClick={() => void organizationsQuery.refetch()}
          >
            Try again
          </button>
        </section>
      ) : null}
      {list && list.items.length === 0 ? (
        <section className="repository-state repository-empty-state">
          <p className="eyebrow">A shared beginning</p>
          <h2 id="organization-empty-title">No organizations yet.</h2>
          <p>Create an organization when a project needs shared membership and ownership.</p>
          <Link className="repository-secondary-action" to="/app/organizations/new">
            Create your first organization
          </Link>
        </section>
      ) : null}
      {list && list.items.length > 0 ? (
        <section className="repository-list-section" aria-labelledby="organization-list-title">
          <div className="repository-list-heading">
            <h2 id="organization-list-title">Your organizations</h2>
            <p>{list.total} total</p>
          </div>
          <ul className="repository-list">
            {list.items.map((organization) => (
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
        </section>
      ) : null}
    </main>
  );
}
