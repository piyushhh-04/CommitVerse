import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { ThemeToggle } from "../theme/ThemeProvider";

export function AuthenticatedShell() {
  const auth = useAuth();
  const location = useLocation();
  const [isNavigationOpen, setIsNavigationOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const previousPathname = useRef(location.pathname);
  const focusDestinationHeading = useRef(false);
  const isLogoutPending = auth.operation.status === "pending" && auth.operation.action === "logout";
  const logoutError =
    auth.operation.status === "error" && auth.operation.action === "logout"
      ? auth.operation.error
      : null;

  useEffect(() => {
    if (!isNavigationOpen) return;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsNavigationOpen(false);
        menuButtonRef.current?.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isNavigationOpen]);

  useLayoutEffect(() => {
    const pathnameChanged = previousPathname.current !== location.pathname;
    previousPathname.current = location.pathname;
    if (!pathnameChanged || !focusDestinationHeading.current) return;

    focusDestinationHeading.current = false;
    document.getElementById("foundation-title")?.focus();
  }, [location.pathname]);

  if (auth.status !== "authenticated") return null;

  async function handleLogout() {
    try {
      await auth.logout();
    } catch {
      // AuthProvider reconciles the session and exposes the sanitized error.
    }
  }

  const navClass = `app-navigation${isNavigationOpen ? " is-open" : ""}`;

  function closeNavigation(destination: string, event: MouseEvent<HTMLAnchorElement>) {
    const target = event.currentTarget.target;
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.altKey ||
      event.ctrlKey ||
      event.shiftKey ||
      (target !== "" && target.toLowerCase() !== "_self")
    ) {
      return;
    }

    if (isNavigationOpen && window.matchMedia("(max-width: 760px)").matches) {
      if (location.pathname === destination) {
        menuButtonRef.current?.focus();
      } else {
        focusDestinationHeading.current = true;
      }
    }
    setIsNavigationOpen(false);
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header-inner">
          <Link className="brand app-brand" to="/app" aria-label="CommitVerse Hub dashboard">
            <span className="brand-mark" aria-hidden="true">
              C
            </span>
            <span>CommitVerse</span>
            <span className="app-brand-suffix">HUB</span>
          </Link>

          <button
            ref={menuButtonRef}
            className="app-menu-toggle"
            type="button"
            aria-label={
              isNavigationOpen ? "Close application navigation" : "Open application navigation"
            }
            aria-expanded={isNavigationOpen}
            aria-controls="app-navigation"
            onClick={() => setIsNavigationOpen((open) => !open)}
          >
            <span />
            <span />
          </button>

          <nav className={navClass} id="app-navigation" aria-label="Application navigation">
            <div className="app-navigation-links">
              <NavLink to="/app" end onClick={(event) => closeNavigation("/app", event)}>
                Dashboard
              </NavLink>
              <NavLink
                to="/app/repositories"
                onClick={(event) => closeNavigation("/app/repositories", event)}
              >
                Repositories
              </NavLink>
              <NavLink
                to="/app/organizations"
                onClick={(event) => closeNavigation("/app/organizations", event)}
              >
                Organizations
              </NavLink>
            </div>
            <div className="app-navigation-account">
              <div className="app-user-summary">
                <span className="app-user-name">{auth.user.display_name}</span>
                <span className="app-user-email">{auth.user.email}</span>
              </div>
              <ThemeToggle />
              <button
                className="app-logout-button"
                type="button"
                disabled={isLogoutPending}
                aria-busy={isLogoutPending}
                onClick={() => void handleLogout()}
              >
                {isLogoutPending ? "Signing out..." : "Sign out"}
              </button>
            </div>
          </nav>
        </div>
      </header>

      <div className="app-content">
        {logoutError ? (
          <div className="app-operation-error" role="alert">
            <span>{logoutError.message}</span>
            {logoutError.requestId ? <span>Reference: {logoutError.requestId}</span> : null}
          </div>
        ) : null}
        <Outlet />
      </div>
    </div>
  );
}
