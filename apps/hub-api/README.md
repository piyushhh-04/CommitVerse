# CommitVerse Hub API

The Hub API is the local-development FastAPI foundation for CommitVerse Hub.
It is a separate package from CommitVerse Core and currently provides
application composition, validated environment configuration, versioned
health reporting, safe error responses, request IDs, structured request
logging, an optional PostgreSQL persistence foundation, and secure browser
session authentication for the first-party Hub client. The current API includes
registration, login, logout, and current-user resolution flows, with
server-side session tokens and an exact-origin allowlist for state-changing
requests. Authenticated users can create, list, inspect, update, and delete
their own personal repositories; lifecycle operations initialize or remove
bare repositories through CommitVerse Core.
The API also supports organization metadata creation/list/detail/update and
organization membership listing, addition, role changes, removal, leaving, and
ownership transfer. Organization owners and admins can also create, list,
inspect, update, and delete organization-owned repository metadata through
Core-backed HTTP routes. Authenticated users can update their username, display
name, and bio through the CSRF-protected `/api/v1/me` profile route. Repository
owners and organization owners/admins can manage direct user permission grants
through repository permission routes. Authenticated repository content browsing
is implemented for bounded tree, blob, commit-history, commit-detail, and
first-parent diff reads from HEAD, local branches, and direct-commit tags.
Anonymous browsing is supported only for ready public repositories; private
repositories remain non-enumerable. Organization and repository invitation
issuance, listing, revocation, and authenticated email-bound acceptance are
implemented. Invitation tokens are returned only at creation and stored as
hashes; the Hub web app supports organization and repository invitation
creation, listing, revocation, and authenticated acceptance. Tokens must be
shared manually; email delivery is not implemented. Advanced diff workflows
remain future work. The authenticated
user directory exposes only active username/display-name prefix matches and
never returns email addresses.

## Requirements

- Python 3.11 or newer
- The repository-root `.venv`
- The independently installed CommitVerse Core package for repository endpoints
- A configured PostgreSQL database for authentication/repository routes,
  database diagnostics, and migrations

From the repository root, install the package and its test dependencies into
the existing environment:

```sh
.venv/bin/python -m pip install -e "./apps/hub-api[dev]"
.venv/bin/python -m pip install -e "./packages/commitverse-core"
```

## Run locally

Start the development server on loopback:

```sh
.venv/bin/commitverse-hub
```

Alternatively, run the application factory with Uvicorn:

```sh
.venv/bin/uvicorn --factory commitverse_hub.main:create_app \
  --app-dir apps/hub-api/src --host 127.0.0.1 --port 8000 --no-access-log
```

Uvicorn access logging is disabled because invitation tokens are path
parameters. The API's structured request middleware logs only route templates,
not raw paths or tokens. The browser API test server also disables Uvicorn
access logging. No production reverse-proxy, gateway, CDN, or hosted deployment
configuration is checked in or verified; the Vite proxy is for local
development only. Any external logging, tracing, or analytics layer must
redact invitation-token-bearing path segments before recording requests and
must never store raw invitation tokens.

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
| `HUB_ALLOWED_ORIGINS` / `HUB_CSRF_ALLOWED_ORIGINS` | `http://localhost:3000,...` | Exact allow-list of browser origins accepted for state-changing auth requests. |
| `HUB_SESSION_COOKIE_NAME` | `commitverse_session` | Opaque browser-session cookie name. |
| `HUB_SESSION_COOKIE_SECURE` | `true` | Secure-cookie flag; cannot be disabled in production. |
| `HUB_SESSION_COOKIE_HTTPONLY` | `true` | Must remain enabled. |
| `HUB_SESSION_COOKIE_SAMESITE` | `lax` | `lax`, `strict`, or `none`; `none` requires Secure. |
| `HUB_SESSION_COOKIE_PATH` | `/` | Cookie path. |
| `HUB_SESSION_COOKIE_DOMAIN` | unset | Optional explicit host scope; wildcard domains are rejected. |
| `HUB_SESSION_COOKIE_MAX_AGE` | `2592000` | Cookie lifetime in seconds, limited to one year. |
| `HUB_REPOSITORY_STORAGE_ROOT` | `~/.commitverse/repositories` | Dedicated private directory for bare repositories; must be outside the source tree. |

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
application startup. The schema defines metadata and constraints; the
authentication and personal-repository workflows are implemented in Hub
application code. Future model changes require reviewed Alembic revisions; do
not use `Base.metadata.create_all()` as a substitute.
`alembic check` compares the connected schema with model metadata and requires
the configured database URL. Migration `40037b3edad7` was verified on
PostgreSQL 17.11: SQLAlchemy connected to `commitverse` as `commitverse_app`,
PostgreSQL reported all nine application tables plus `alembic_version`, and
Alembic upgrade, downgrade to `base`, re-upgrade, and `current` succeeded.
The initial revision is `40037b3edad7`. The current source migration head is
`a7d4d1d1f7ed` (`add_repository_deleted_state`). The recorded PostgreSQL
validation predates that second revision; it does not establish that the
current head has been applied to the configured PostgreSQL database. Check
the actual database with `alembic current`.

The engine and synchronous session factory are application-lifecycle
resources. Use `transactional_session` only where the caller explicitly owns a
transaction; it commits on success, rolls back on exceptions, and closes the
session. Do not call synchronous database operations directly from an async
route: use a synchronous route/dependency or bounded worker-thread execution.

## Authentication security primitives and workflows

`commitverse_hub.auth` provides Argon2id password hashing/verification with
rehash detection, 256-bit opaque session token generation and SHA-256 storage
hashing, session lifecycle persistence, cookie set/clear helpers, and
session-bound CSRF token and exact-Origin validation utilities. Password
hashes and raw session tokens are not logged or returned through response
schemas. Session persistence helpers participate in the caller's SQLAlchemy
transaction and do not commit independently.

The API implements first-party browser registration, login, logout, and
current-user resolution under `/api/v1/auth` and `/api/v1/me`. The session
cookie is `HttpOnly`, `Secure` by default, `SameSite=Lax`, and scoped to `/`;
its server-side session expires according to the configured cookie max age.
The raw 256-bit session token is returned only in the cookie and stored in the
database only as a SHA-256 hash. Logging does not include raw session tokens,
passwords, or CSRF tokens.

Registration always requires an exact allow-listed `Origin`. Login and logout
also require an exact allow-listed `Origin` on every request. If their cookie
identifies an active session, they additionally require a valid
session-bound `X-CSRF-Token`. If the cookie is absent, malformed, expired, or
revoked, login follows the Origin-protected pre-authentication flow and logout
clears the stale cookie after Origin validation. A database/session-store
failure during active-session lookup returns a service error; it is not
treated as evidence of a stale session and does not bypass CSRF validation.
Login creates a new session without revoking other active sessions. Logout
revokes only the active session represented by the current cookie.

Successful registration and login return a fresh `X-CSRF-Token` response
header. An authenticated `GET /api/v1/me` returns the same user JSON as before
and a newly generated `X-CSRF-Token` header bound to the validated session.
API responses include `Cache-Control: no-store` to prevent browser or
intermediary caches from reusing session-scoped data across accounts. Invalid
sessions receive neither a CSRF token nor an authenticated user response. The
token is not included in JSON. A browser client should retain it only in memory
and request `/api/v1/me` after a page reload to restore it; it must not persist
the token in browser storage or a JavaScript-readable cookie. Anonymous public
browsing remains read-only; the Hub client retains permitted public results in
its separate in-memory query cache.

Authenticated mutation routes require both the exact allow-listed `Origin`
and the session-bound `X-CSRF-Token`. CORS configuration is not a substitute
for CSRF validation. Active-session lookup rejects disabled accounts;
account-disable workflows must also revoke the account's existing sessions.

## Personal repositories

The current repository API is owner-only and stores metadata separately from
Core repository contents:

- `POST /api/v1/repositories` creates a personal bare repository.
- `GET /api/v1/repositories` lists the authenticated user's ready repositories
  (`limit` 1–100 and bounded `offset`).
- `GET /api/v1/repositories/{repository_id}` returns owner-only metadata.
- `PATCH /api/v1/repositories/{repository_id}` updates name, description, or
  visibility.
- `DELETE /api/v1/repositories/{repository_id}` removes the verified bare
  repository and retains a metadata tombstone.

Metadata and mutation routes require a valid active browser session. Browse
routes allow anonymous access only after verifying public repository visibility.
Mutations also require
the exact allow-listed `Origin` and a session-bound `X-CSRF-Token`. Responses
never include a filesystem path or storage key. `public` repositories support
anonymous read-only browsing when ready; private repositories require
authorization. Authorized users can
read the current HEAD tree, bounded text blobs, and recent commit history.
Organization repository routes support create/list/detail/update/delete for
current organization owners and admins. Ordinary organization membership does
not imply repository visibility; direct grant management is restricted to
repository managers. Authorized browsing supports HEAD, validated local
branches/tags, bounded trees/blobs/history, and reachable commit details; diff
browsing remains future work.

The storage root is created with private permissions when needed. Repository
creation publishes a verified Core bare repository from a temporary sibling
directory. Deletion commits metadata as `deleting` before removing storage,
then finalizes the tombstone as `deleted`; failed steps remain retryable.
Organization-owned operations lock the organization before the repository,
and current membership/role is revalidated within the owning transaction.
Database row locks coordinate metadata transitions across PostgreSQL workers,
but database and filesystem operations are not atomic and the local filesystem
does not provide multi-host storage guarantees.

## Organizations and memberships

Authenticated organization routes support create, list, detail, and metadata
update. Members can list their organization roster and read organization
metadata; members of active organizations can also leave. Owners can add
admins or members, change non-owner roles, remove admins or members, and
transfer ownership after verifying their current password. Admins can update
metadata, add members only, and remove members only; ordinary members cannot
administer membership. Organization
creation inserts its creator as owner in the same transaction. The service
preserves at least one active owner and writes audit events atomically with
organization/membership changes.

Organization mutations validate the actor's active account and current role
inside the transaction. Mutations on an existing organization lock its row
before membership and user rows; multi-user operations acquire user rows in
ascending UUID order. The organization state values are `active` and `disabled`;
disabled organizations remain readable to members but reject mutations.
Disable/enable operations and terminal organization deletion are not
implemented. Direct membership addition requires an existing user ID; the
organization invitation API separately supports email-bound invitations.

Hub has no account-deactivation workflow. The active-owner invariant applies
to organization mutations using this locking protocol; independent account
state changes that bypass it are not covered. Any future account-deactivation
workflow must coordinate with organization ownership changes.

Organization-owned repository creation, listing, metadata updates, and deletion
use the shared lifecycle service through HTTP routes. No ordinary organization
member receives implicit repository access.

## Tests

From the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  -p no:cacheprovider apps/hub-api/tests -q -rs
```

The default test suite uses an in-process HTTP client and injected resources;
it requires neither a running PostgreSQL server nor external network access.
Authentication and session tests use isolated SQLite databases by default.
Set `HUB_TEST_DATABASE_URL` to run the PostgreSQL session-persistence,
repository lifecycle, organization concurrency, and invitation single-use
concurrency tests against isolated schemas/resources. Point it only at a
dedicated test database; never use a development or production database. In particular,
`test_postgresql_concurrent_owner_leaves_preserve_one_eligible_owner` is
skipped without that variable, as is
`test_postgresql_opposite_multi_user_mutations_do_not_deadlock`,
`test_postgresql_concurrent_organization_invitation_acceptance_is_single_use`,
`test_postgresql_concurrent_repository_invitation_acceptance_is_single_use`,
and `test_postgresql_repository_invitation_rechecks_lifecycle_after_lock_wait`.
SQLite results do not verify row-lock concurrency. Report skipped PostgreSQL tests
rather than claiming acceptance. The repository integration test exercises
create, list/detail, update, Core bare-repository verification, and delete,
then rolls back its schema transaction. Duplicate names and retry behavior
are covered by isolated SQLite tests. Do not claim PostgreSQL integration
verification when these tests are skipped.
For example, after configuring `HUB_DATABASE_URL` for the local server:

```sh
HUB_TEST_DATABASE_URL="$HUB_DATABASE_URL" PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m pytest -p no:cacheprovider \
  apps/hub-api/tests/test_auth.py \
  apps/hub-api/tests/test_repositories.py -q
```

Schema tests apply, downgrade, and re-apply the migration against a temporary
SQLite database, then compare SQLAlchemy metadata and inspect indexes.
SQLite/Alembic cannot reflect expression-based indexes, so their created SQL
is checked directly. Historical PostgreSQL verification covered initial
revision `40037b3edad7`; during final release-readiness verification current
head `a7d4d1d1f7ed` was applied to a dedicated isolated PostgreSQL 17.11
database. This local result does not establish hosted deployment readiness.

## Current limitations

Organization metadata, membership, owner/admin organization-repository metadata,
direct grant management, and bounded authorized repository browsing APIs are
implemented for HEAD, validated local branches/tags, and reachable commit
details. Organization and repository invitation APIs and web
create/list/revoke/accept workflows are implemented without email delivery;
tokens are shared manually. Public repositories support bounded anonymous
read-only browsing by ID, but there is no public repository discovery or
public repository metadata endpoint. Advanced diff browsing,
automated reconciliation, cross-process repository
coordination, network Git protocols, and deployment are not implemented. There are no
configured rate limits or production backup/restore procedures. Local
PostgreSQL validation does not establish cloud deployment readiness; hosting
and repository storage remain subject to the project's strict ₹0 policy.
