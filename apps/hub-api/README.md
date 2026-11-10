# CommitVerse Hub API

The Hub API is the local-development FastAPI foundation for CommitVerse Hub.
It is a separate package from CommitVerse Core and currently provides
application composition, validated environment configuration, versioned
health reporting, safe error responses, request IDs, structured request
logging, an optional PostgreSQL persistence foundation, and reusable
authentication security primitives. No registration, login, logout, or
authorization workflows are implemented; the initial SQLAlchemy schema
defines the nine approved metadata tables.

## Requirements

- Python 3.11 or newer
- The repository-root `.venv`
- A local PostgreSQL server only when using database diagnostics or migrations

From the repository root, install the package and its test dependencies into
the existing environment:

```sh
.venv/bin/python -m pip install -e "./apps/hub-api[dev]"
```

## Run locally

Start the development server on loopback:

```sh
.venv/bin/commitverse-hub
```

Alternatively, run the application factory with Uvicorn:

```sh
.venv/bin/uvicorn --factory commitverse_hub.main:create_app \
  --app-dir apps/hub-api/src --host 127.0.0.1 --port 8000
```

The server does not open a database connection or connect to CommitVerse Core
during startup. When configured, it creates a small connection pool during
application lifespan startup and disposes it on shutdown. Press `Ctrl+C` to
stop the local server cleanly.

## Health endpoint

`GET /api/v1/health` returns HTTP 200 when the API process is operational:

```json
{
  "status": "ok",
  "service": "commitverse-hub"
}
```

This endpoint does not claim that PostgreSQL, repository storage, or Core is
available.

`GET /api/v1/health/database` runs `SELECT 1` through the bounded connection
pool in a worker thread. It returns:

```json
{
  "status": "ok",
  "service": "commitverse-hub-database"
}
```

when configured and reachable, or HTTP 503 with `"status": "unavailable"` when
the database is not configured or the check fails. This diagnostic does not
verify migration state or application feature health.

## Configuration

Settings are read from environment variables at application creation. No
`.env` file is loaded. Database configuration is optional for API startup and
non-database tests.

| Variable | Default | Description |
|---|---|---|
| `HUB_APPLICATION_NAME` | `CommitVerse Hub` | FastAPI application title. |
| `HUB_API_VERSION` | `0.1.0` | Application version in API metadata. |
| `HUB_ENVIRONMENT` | `development` | One of `development`, `testing`, or `production`. |
| `HUB_DEBUG` | `false` | Enables FastAPI debug mode; forbidden in production. |
| `HUB_LOG_LEVEL` | `INFO` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. |
| `HUB_API_PREFIX` | `/api/v1` | Absolute URL path prefix for the versioned API. |
| `HUB_DATABASE_URL` | unset | PostgreSQL URL using `postgresql+psycopg://`; required for database checks and migrations. |
| `HUB_SESSION_COOKIE_NAME` | `commitverse_session` | Opaque browser-session cookie name. |
| `HUB_SESSION_COOKIE_SECURE` | `true` | Secure-cookie flag; cannot be disabled in production. |
| `HUB_SESSION_COOKIE_HTTPONLY` | `true` | Must remain enabled. |
| `HUB_SESSION_COOKIE_SAMESITE` | `lax` | `lax`, `strict`, or `none`; `none` requires Secure. |
| `HUB_SESSION_COOKIE_PATH` | `/` | Cookie path. |
| `HUB_SESSION_COOKIE_DOMAIN` | unset | Optional explicit host scope; wildcard domains are rejected. |
| `HUB_SESSION_COOKIE_MAX_AGE` | `2592000` | Cookie lifetime in seconds, limited to one year. |

Invalid values fail application creation with a clear configuration error.
Unexpected HTTP errors always return a generic response; exception details
remain in server logs.

## Local PostgreSQL and migrations

The verified local development setup uses PostgreSQL 17.11 installed natively
with Homebrew on macOS/Apple Silicon M2. Start the Homebrew service and create
a dedicated database and role if they do not already exist. For a standard
versioned Homebrew formula:

```sh
brew install postgresql@17
brew services start postgresql@17
createuser --pwprompt commitverse_app
createdb --owner=commitverse_app commitverse
```

The verified database is `commitverse`, owned by `commitverse_app`, at
`localhost:5432`. Configure `HUB_DATABASE_URL` in the local shell with the
URL-encoded password, for example:

```sh
export HUB_DATABASE_URL='postgresql+psycopg://commitverse_app:<URL-encoded-password>@localhost:5432/commitverse'
```

This is a placeholder only. Never put the real password or URL in source
control, documentation, or an `.env` file. No PostgreSQL authentication
settings were changed for this documentation. Docker is not required for the
current local setup; it remains an optional future infrastructure tool. No
cloud database is needed for local development.

The connection pool is limited to two connections with no overflow;
connection, pool-wait, and statement timeouts bound the diagnostic query.

Run Alembic commands from `apps/hub-api/`:

```sh
../../.venv/bin/alembic -c alembic.ini current
../../.venv/bin/alembic -c alembic.ini upgrade head
../../.venv/bin/alembic -c alembic.ini check
```

Alembic uses `HUB_DATABASE_URL` and `commitverse_hub.db.base.Base.metadata`.
Migration `40037b3edad7` (`create_initial_hub_schema`) creates the initial
schema for users, profiles, organizations, organization memberships,
repositories, direct repository permissions, invitations, sessions, and
audit events. Migration `upgrade`/`downgrade` is explicit and is never run by
application startup. The schema contains no authentication or authorization
workflows. Future model changes require reviewed Alembic revisions; do not use
`Base.metadata.create_all()` as a substitute.
`alembic check` compares the connected schema with model metadata and requires
the configured database URL. Migration `40037b3edad7` was verified on
PostgreSQL 17.11: SQLAlchemy connected to `commitverse` as `commitverse_app`,
PostgreSQL reported all nine application tables plus `alembic_version`, and
Alembic upgrade, downgrade to `base`, re-upgrade, and `current` succeeded.
The verified revision is `40037b3edad7 (head)`.

The engine and synchronous session factory are application-lifecycle
resources. Use `transactional_session` only where the caller explicitly owns a
transaction; it commits on success, rolls back on exceptions, and closes the
session. Do not call synchronous database operations directly from an async
route: use a synchronous route/dependency or bounded worker-thread execution.

## Authentication security primitives

`commitverse_hub.auth` provides Argon2id password hashing/verification with
rehash detection, 256-bit opaque session token generation and SHA-256 storage
hashing, session lifecycle persistence, cookie set/clear helpers, and
session-bound CSRF token and exact-Origin validation utilities. Password
hashes and raw session tokens are not logged or returned through response
schemas. Session persistence helpers participate in the caller's SQLAlchemy
transaction and do not commit independently.

These are reusable foundations, not authentication workflows. There are no
registration, login, logout, password-reset, email-verification, current-user,
or authorization endpoints. Future routes must add generic failure responses,
rate limiting, session rotation, authenticated principal resolution, and an
explicit exact-Origin allowlist. CORS configuration is not a substitute for
CSRF validation. Active-session lookup rejects disabled accounts; account
disable workflows must also revoke the account's existing sessions.

## Tests

From the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  -p no:cacheprovider apps/hub-api/tests -q
```

The default test suite uses an in-process HTTP client and injected resources;
it requires neither a running PostgreSQL server nor external network access.
Authentication and session tests use isolated SQLite databases by default.
Set `HUB_TEST_DATABASE_URL` to run the PostgreSQL session-lifecycle test; it
creates a unique schema in a transaction and rolls the entire schema back.
This test has been run against the verified local PostgreSQL 17.11 database.
For example, after configuring `HUB_DATABASE_URL` for the local server:

```sh
HUB_TEST_DATABASE_URL="$HUB_DATABASE_URL" PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m pytest -p no:cacheprovider \
  apps/hub-api/tests/test_auth.py -q
```

Schema tests apply, downgrade, and re-apply the migration against a temporary
SQLite database, then compare SQLAlchemy metadata and inspect indexes.
SQLite/Alembic cannot reflect expression-based indexes, so their created SQL
is checked directly. The isolated SQLite tests complement, but do not
substitute for, the completed PostgreSQL migration verification above.

## Current limitations

The persistence schema and authentication utilities do not implement
registration/login/logout, password-reset or email-verification workflows,
session middleware or principal resolution, authorization workflows,
organization management, repository operations, the Core adapter, network Git
protocols, a frontend, or deployment. Local PostgreSQL validation does not
establish cloud deployment readiness; hosting and repository storage remain
subject to the project's strict ₹0 policy.
