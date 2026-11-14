import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "./AuthContext";

export function ProtectedRoute() {
  const auth = useAuth();
  const location = useLocation();

  if (auth.status === "loading") {
    return (
      <main className="foundation-page">
        <p role="status" aria-live="polite">
          Checking your session...
        </p>
      </main>
    );
  }

  if (auth.status === "error") {
    return (
      <main className="foundation-page">
        <section className="foundation-content" role="alert">
          <p className="eyebrow">Session</p>
          <h1>We could not verify your session.</h1>
          <p>{auth.error.message}</p>
          <button
            className="foundation-action"
            type="button"
            onClick={() => void auth.retrySession()}
          >
            Try again
          </button>
        </section>
      </main>
    );
  }

  if (auth.status === "anonymous") {
    return <Navigate to="/login" replace state={{ from: location, reason: "session-required" }} />;
  }

  return <Outlet />;
}
