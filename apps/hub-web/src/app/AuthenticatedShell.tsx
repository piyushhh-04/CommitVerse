import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { ThemeToggle } from "../theme/ThemeProvider";
import { useMobileNavigation } from "./useMobileNavigation";

function requestsHeadingFocus(state: unknown): boolean {
  return (
    typeof state === "object" &&
    state !== null &&
    "focusDestinationHeading" in state &&
    state.focusDestinationHeading === true
  );
}

export function AuthenticatedShell() {
  const auth = useAuth();
  const location = useLocation();
  const [isNavigationOpen, setIsNavigationOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const navigationRef = useRef<HTMLElement>(null);
  const previousPathname = useRef(location.pathname);
  const focusDestinationHeading = useRef(false);
  const isLogoutPending = auth.operation.status === "pending" && auth.operation.action === "logout";
  const logoutError =
    auth.operation.status === "error" && auth.operation.action === "logout"
      ? auth.operation.error
      : null;

  useMobileNavigation(isNavigationOpen, menuButtonRef, navigationRef, () =>
    setIsNavigationOpen(false),
  );

  useEffect(() => {
    setIsNavigationOpen(false);
  }, [location.pathname]);

  useLayoutEffect(() => {
    const pathnameChanged = previousPathname.current !== location.pathname;
    previousPathname.current = location.pathname;
    if (
      !pathnameChanged ||
      (!focusDestinationHeading.current && !requestsHeadingFocus(location.state))
    ) {
      return;
    }

    focusDestinationHeading.current = false;
    const heading = document.getElementById("foundation-title");
    if (heading?.getAttribute("aria-busy") !== "true") heading?.focus();
  }, [location.pathname, location.state]);

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

    const isCompactNavigation = window.matchMedia("(max-width: 1023px)").matches;
    if (location.pathname === destination) {
      if (isNavigationOpen && isCompactNavigation) {
        menuButtonRef.current?.focus();
      }
    } else if (isCompactNavigation) {
      focusDestinationHeading.current = true;
    }
    setIsNavigationOpen(false);
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#app-main">
        Skip to content
      </a>
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
            <svg viewBox="0 0 20 20" aria-hidden="true">
              {isNavigationOpen ? (
                <path d="m5 5 10 10M15 5 5 15" />
              ) : (
                <path d="M3 6h14M3 10h14M3 14h14" />
              )}
            </svg>
          </button>

          <nav
            ref={navigationRef}
            className={navClass}
            id="app-navigation"
            aria-label="Application navigation"
          >
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
                <span className="app-user-username">@{auth.user.username}</span>
                <span className="app-user-email">{auth.user.email}</span>
              </div>
              <Link className="app-account-link" to="/app/settings/profile">
                Profile settings
              </Link>
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

      <div className="app-content" id="app-main" tabIndex={-1}>
        {logoutError ? (
          <div className="app-operation-error" role="alert">
            <span>{logoutError.message}</span>
            {logoutError.requestId ? <span>Reference: {logoutError.requestId}</span> : null}
          </div>
        ) : null}
        <Outlet key={auth.user.id} />
      </div>
    </div>
  );
}
