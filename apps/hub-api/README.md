# CommitVerse Hub API

The Hub API is the local-development FastAPI foundation for CommitVerse Hub.
It is a separate package from CommitVerse Core and currently provides
application composition, validated environment configuration, versioned
health reporting, safe error responses, request IDs, structured request
logging, and an optional PostgreSQL persistence foundation. No application
tables are defined yet.

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

Invalid values fail application creation with a clear configuration error.
Unexpected HTTP errors always return a generic response; exception details
remain in server logs.

## Local PostgreSQL and migrations

Use an installed local PostgreSQL server; no Docker or cloud database is
required. Create a dedicated local development database and provide its URL
only in your shell environment. For example, from the repository root:

```sh
export HUB_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/commitverse_hub'
```

Do not put real credentials in source control or `alembic.ini`. SQLAlchemy
accepts URL-encoded credentials. The connection pool is limited to two
connections with no overflow; connection, pool-wait, and statement timeouts
bound the diagnostic query.

Run Alembic commands from `apps/hub-api/`:

```sh
../../.venv/bin/alembic -c alembic.ini current
../../.venv/bin/alembic -c alembic.ini upgrade head
```

Alembic uses `HUB_DATABASE_URL` and `commitverse_hub.db.base.Base.metadata`.
Migrations are never run by application startup. No initial revision or
application tables exist yet. Add model modules and a reviewed migration in a
later milestone before treating the database schema as established.

The engine and synchronous session factory are application-lifecycle
resources. Use `transactional_session` only where the caller explicitly owns a
transaction; it commits on success, rolls back on exceptions, and closes the
session. Do not call synchronous database operations directly from an async
route: use a synchronous route/dependency or bounded worker-thread execution.

## Tests

From the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  -p no:cacheprovider apps/hub-api/tests -q
```

The default test suite uses an in-process HTTP client and injected resources;
it requires neither a running PostgreSQL server nor external network access.
Tests of transaction mechanics do not claim PostgreSQL driver interoperability.

## Current limitations

This is only the persistence foundation. It does not define application
models, authentication, sessions, authorization, organizations, repository
operations, the Core adapter, network Git protocols, a frontend, or
deployment. A live PostgreSQL server is not bundled or provisioned. Database
provisioning remains local/deferred under the project's strict ₹0 policy; this
package does not establish cloud deployment readiness.
