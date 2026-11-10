# CommitVerse Hub API

The Hub API is the local-development FastAPI foundation for CommitVerse Hub.
It is a separate package from CommitVerse Core and currently provides
application composition, validated environment configuration, versioned
health reporting, safe error responses, request IDs, and request logging.

## Requirements

- Python 3.11 or newer
- The repository-root `.venv`

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

The server does not connect to a database or CommitVerse Core during startup.

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

## Configuration

Settings are read from environment variables at application creation. No
`.env` file is loaded.

| Variable | Default | Description |
|---|---|---|
| `HUB_APPLICATION_NAME` | `CommitVerse Hub` | FastAPI application title. |
| `HUB_API_VERSION` | `0.1.0` | Application version in API metadata. |
| `HUB_ENVIRONMENT` | `development` | One of `development`, `testing`, or `production`. |
| `HUB_DEBUG` | `false` | Enables FastAPI debug mode; forbidden in production. |
| `HUB_LOG_LEVEL` | `INFO` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. |
| `HUB_API_PREFIX` | `/api/v1` | Absolute URL path prefix for the versioned API. |

Invalid values fail application creation with a clear configuration error.
Unexpected HTTP errors always return a generic response; exception details
remain in server logs.

## Tests

From the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  -p no:cacheprovider apps/hub-api/tests -q
```

The tests use an in-process HTTP client and require neither PostgreSQL nor
network access.

## Current limitations

This is only the backend foundation. It does not implement database
integration, authentication, sessions, authorization, organizations,
repository operations, the Core adapter, network Git protocols, a frontend,
or deployment. Hub development remains local under the project's strict ₹0
policy; this package does not establish cloud deployment readiness.
