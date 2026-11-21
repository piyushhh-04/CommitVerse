import { Link, useParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { RepositoryBrowsePanel } from "../components/RepositoryBrowsePanel";

export function PublicRepositoryPage() {
  const { repositoryId = "" } = useParams();

  return (
    <main className="repository-page repository-detail-page">
      <Link className="repository-back-link" to="/">
        <span aria-hidden="true">←</span> CommitVerse
      </Link>
      <header className="repository-detail-header">
        <div>
          <h1 id="foundation-title" tabIndex={-1}>
            Repository contents
          </h1>
          <p className="repository-detail-description">
            Repository ID: <code>{repositoryId}</code>
          </p>
        </div>
        <Link className="repository-secondary-action" to="/login">
          Sign in to your workspace
        </Link>
      </header>
      <p className="repository-visibility-note">
        This page uses anonymous, read-only API requests and shows content only when the repository
        is publicly readable. The current API does not expose repository name, description, or owner
        metadata.
      </p>
      <RepositoryBrowsePanel repositoryId={repositoryId} userId="" anonymous />
    </main>
  );
}

export function AuthenticatedRepositoryBrowserPage() {
  const { repositoryId = "" } = useParams();
  const auth = useAuth();
  const userId = auth.status === "authenticated" ? auth.user.id : "";

  if (!userId) return null;

  return (
    <main className="repository-page repository-detail-page">
      <Link className="repository-back-link" to="/app">
        <span aria-hidden="true">←</span> Workspace
      </Link>
      <header className="repository-detail-header">
        <div>
          <h1 id="foundation-title" tabIndex={-1}>
            Repository contents
          </h1>
          <p className="repository-detail-description">
            Repository ID: <code>{repositoryId}</code>
          </p>
        </div>
      </header>
      <RepositoryBrowsePanel repositoryId={repositoryId} userId={userId} />
    </main>
  );
}
