import { useState, type FormEvent, type ChangeEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { LoginCredentials, RegistrationDetails } from "../auth/types";
import { ThemeToggle } from "../theme/ThemeProvider";

type AuthFormMode = "login" | "register";
type FieldErrors = Partial<Record<"email" | "password" | "username" | "display_name", string>>;

const EMAIL_PATTERN = /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}$/;

function getReturnPath(state: unknown): string {
  if (typeof state !== "object" || state === null || !("from" in state)) return "/app";
  const from = state.from;
  if (typeof from !== "object" || from === null || !("pathname" in from)) return "/app";

  const pathname = from.pathname;
  const search = "search" in from ? from.search : "";
  const hash = "hash" in from ? from.hash : "";
  if (
    typeof pathname !== "string" ||
    !pathname.startsWith("/") ||
    pathname.startsWith("//") ||
    pathname.includes("\\") ||
    pathname === "/login" ||
    pathname === "/register"
  ) {
    return "/app";
  }

  return `${pathname}${typeof search === "string" && search.startsWith("?") ? search : ""}${
    typeof hash === "string" && hash.startsWith("#") ? hash : ""
  }`;
}

function getFieldErrors(mode: AuthFormMode, data: FormData): FieldErrors {
  const email = String(data.get("email") ?? "").trim();
  const password = String(data.get("password") ?? "");
  const errors: FieldErrors = {};

  if (!email || !EMAIL_PATTERN.test(email)) {
    errors.email = "Enter a valid email address.";
  }
  if (!password) {
    errors.password = "Enter your password.";
  } else if (
    Array.from(password).length > 1024 ||
    new TextEncoder().encode(password).length > 1024
  ) {
    errors.password = "Password exceeds the maximum supported length.";
  }

  if (mode === "register") {
    const username = String(data.get("username") ?? "");
    const displayName = String(data.get("display_name") ?? "");
    if (!username.trim()) {
      errors.username = "Enter a username.";
    } else if (Array.from(username).length > 39) {
      errors.username = "Username must be 39 characters or fewer.";
    }
    if (Array.from(displayName).length > 120) {
      errors.display_name = "Display name must be 120 characters or fewer.";
    }
  }

  return errors;
}

function ApiErrorMessage({ error }: { error: ApiError }) {
  return (
    <div className="account-error" role="alert">
      <p>{error.message}</p>
      {error.details ? (
        <ul>
          {error.details.map((detail, index) => (
            <li key={`${detail.field}-${detail.code}-${index}`}>
              {detail.field ? `${detail.field}: ` : ""}
              {detail.message}
            </li>
          ))}
        </ul>
      ) : null}
      {error.requestId ? (
        <p className="account-error-reference">Reference: {error.requestId}</p>
      ) : null}
    </div>
  );
}

function AuthForm({ mode }: { mode: AuthFormMode }) {
  const auth = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [showPassword, setShowPassword] = useState(false);
  const isRegister = mode === "register";
  const action = isRegister ? "register" : "login";
  const isPending = auth.operation.status === "pending" && auth.operation.action === action;
  const operationError =
    auth.operation.status === "error" && auth.operation.action === action
      ? auth.operation.error
      : null;
  const destination = getReturnPath(location.state);
  const isProtectedDestination =
    typeof location.state === "object" &&
    location.state !== null &&
    "reason" in location.state &&
    location.state.reason === "session-required";

  if (auth.status === "authenticated") {
    return <Navigate to={destination} replace />;
  }

  function clearFieldError(event: ChangeEvent<HTMLInputElement>) {
    const field = event.currentTarget.name as keyof FieldErrors;
    setFieldErrors((current) => {
      if (!(field in current)) return current;
      const next = { ...current };
      delete next[field];
      return next;
    });
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const errors = getFieldErrors(mode, data);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;

    const credentials: LoginCredentials = {
      email: String(data.get("email") ?? "").trim(),
      password: String(data.get("password") ?? ""),
    };

    try {
      if (isRegister) {
        const username = String(data.get("username") ?? "").trim();
        const displayName = String(data.get("display_name") ?? "").trim();
        const details: RegistrationDetails = {
          ...credentials,
          username,
          ...(displayName ? { display_name: displayName } : {}),
        };
        await auth.register(details);
      } else {
        await auth.login(credentials);
      }
    } catch {
      // AuthProvider exposes the sanitized API error through operation state.
      return;
    }
    form.reset();
    void navigate(destination, { replace: true });
  }

  const title = isRegister ? "Create your account" : "Sign in";
  const operationLabel = isRegister ? "Creating account..." : "Signing in...";

  return (
    <div className="account-page">
      <header className="account-header">
        <Link className="brand account-brand" to="/" aria-label="CommitVerse home">
          <span className="brand-mark" aria-hidden="true">
            C
          </span>
          <span>CommitVerse</span>
        </Link>
        <ThemeToggle />
      </header>
      <main className="account-layout">
        <section className="account-story" aria-labelledby="account-story-title">
          <p className="eyebrow">CommitVerse Hub / Account</p>
          <h1 id="account-story-title">
            A considered home
            <br />
            for your work.
          </h1>
          <p>
            Sign in to continue to your Hub workspace. CommitVerse keeps the local version-control
            foundation distinct from account and collaboration workflows.
          </p>
          <div className="account-story-note">
            <span className="account-story-mark" aria-hidden="true">
              01
            </span>
            <p>Clear foundations. Thoughtful tools. Room to grow.</p>
          </div>
        </section>

        <section className="account-form-panel" aria-labelledby="account-form-title">
          <p className="eyebrow">{isRegister ? "New account" : "Welcome back"}</p>
          <h2 id="account-form-title">{title}</h2>
          <p className="account-form-intro">
            {isRegister
              ? "Create an account to enter your CommitVerse Hub."
              : "Use your CommitVerse account to continue."}
          </p>

          {isProtectedDestination ? (
            <p className="account-session-notice" role="status">
              Sign in is required to continue to your requested page.
            </p>
          ) : null}
          {auth.status === "error" ? (
            <div className="account-error" role="alert">
              <p>
                We could not check for an existing session. You can try again or continue below.
              </p>
              <button
                className="account-text-button"
                type="button"
                onClick={() => void auth.retrySession()}
              >
                Retry session check
              </button>
            </div>
          ) : null}
          {operationError ? <ApiErrorMessage error={operationError} /> : null}
          {Object.keys(fieldErrors).length > 0 ? (
            <div className="account-error account-validation-summary" role="alert">
              <p>Please correct the highlighted fields.</p>
            </div>
          ) : null}

          <form
            className="account-form"
            aria-labelledby="account-form-title"
            aria-busy={isPending}
            noValidate
            onSubmit={(event) => void handleSubmit(event)}
          >
            <div className="account-field">
              <label className="account-field-label" htmlFor="account-email">
                Email address
              </label>
              <input
                id="account-email"
                autoComplete="email"
                autoCapitalize="none"
                disabled={isPending}
                type="email"
                name="email"
                required
                aria-invalid={Boolean(fieldErrors.email)}
                aria-describedby={fieldErrors.email ? "email-error" : undefined}
                onChange={clearFieldError}
              />
              {fieldErrors.email ? (
                <span className="account-field-error" id="email-error">
                  {fieldErrors.email}
                </span>
              ) : null}
            </div>

            {isRegister ? (
              <div className="account-field">
                <label className="account-field-label" htmlFor="account-username">
                  Username
                </label>
                <input
                  id="account-username"
                  autoComplete="username"
                  disabled={isPending}
                  type="text"
                  name="username"
                  required
                  aria-invalid={Boolean(fieldErrors.username)}
                  aria-describedby={fieldErrors.username ? "username-error" : undefined}
                  onChange={clearFieldError}
                />
                {fieldErrors.username ? (
                  <span className="account-field-error" id="username-error">
                    {fieldErrors.username}
                  </span>
                ) : null}
              </div>
            ) : null}

            {isRegister ? (
              <div className="account-field">
                <label className="account-field-label" htmlFor="account-display-name">
                  Display name <span className="account-optional">(optional)</span>
                </label>
                <input
                  id="account-display-name"
                  autoComplete="name"
                  disabled={isPending}
                  type="text"
                  name="display_name"
                  aria-invalid={Boolean(fieldErrors.display_name)}
                  aria-describedby={fieldErrors.display_name ? "display-name-error" : undefined}
                  onChange={clearFieldError}
                />
                {fieldErrors.display_name ? (
                  <span className="account-field-error" id="display-name-error">
                    {fieldErrors.display_name}
                  </span>
                ) : null}
              </div>
            ) : null}

            <div className="account-field">
              <label className="account-field-label" htmlFor="account-password">
                Password
              </label>
              <span className="account-password-control">
                <input
                  id="account-password"
                  autoComplete={isRegister ? "new-password" : "current-password"}
                  disabled={isPending}
                  type={showPassword ? "text" : "password"}
                  name="password"
                  required
                  aria-invalid={Boolean(fieldErrors.password)}
                  aria-describedby={fieldErrors.password ? "password-error" : undefined}
                  onChange={clearFieldError}
                />
                <button
                  className="account-password-toggle"
                  type="button"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  aria-pressed={showPassword}
                  disabled={isPending}
                  onClick={() => setShowPassword((visible) => !visible)}
                >
                  {showPassword ? "Hide" : "Show"}
                </button>
              </span>
              {fieldErrors.password ? (
                <span className="account-field-error" id="password-error">
                  {fieldErrors.password}
                </span>
              ) : null}
            </div>

            <button className="account-submit" type="submit" disabled={isPending}>
              {isPending ? operationLabel : title}
            </button>
          </form>

          <p className="account-switch">
            {isRegister ? "Already have an account?" : "New to CommitVerse?"}{" "}
            <Link
              to={isRegister ? "/login" : "/register"}
              state={location.state}
              aria-label={isRegister ? "Sign in to your account" : "Create an account"}
            >
              {isRegister ? "Sign in" : "Create an account"}
            </Link>
          </p>
          {auth.status === "loading" ? (
            <p className="account-session-status" role="status" aria-live="polite">
              Checking your existing session...
            </p>
          ) : null}
          <Link className="account-back-link" to="/">
            Return to the public overview
          </Link>
        </section>
      </main>
      <footer className="account-footer">
        <span>Local Hub application foundation</span>
        <span>Sessions are protected by the Hub API</span>
      </footer>
    </div>
  );
}

export default AuthForm;
