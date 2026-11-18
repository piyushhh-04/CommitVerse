# CommitVerse local development

## PostgreSQL and Hub services

Copy the safe local defaults:

```sh
cp .env.example .env
docker compose up --build postgres api worker
```

The API automatically runs `alembic upgrade head` before startup. The database
volume is persistent and Compose does not delete it:

```sh
docker compose ps
curl http://localhost:8000/api/v1/health
```

To run migrations from the host virtual environment:

```sh
export HUB_DATABASE_URL='postgresql+psycopg://commitverse_app:change-this-local-password@localhost:5432/commitverse'
cd apps/hub-api
.venv/bin/alembic upgrade head
```

## CI worker

The worker is also started by the Compose `worker` service. It:

- polls for pending execution records;
- clones the authorized repository with CommitVerse Core;
- executes workflow steps in Docker containers;
- persists logs and success/failure state.

Example workflow:

```yaml
name: python-quality
trigger: push
jobs:
  test:
    image: python:3.12-slim
    timeout: 300
    memory_bytes: 536870912
    environment:
      PYTHONDONTWRITEBYTECODE: "1"
    steps:
      - run: python -m compileall -q .
```

Supported triggers are `push`, `pull_request`, and `manual`. The first
implementation executes jobs serially and does not claim GitHub Actions
compatibility.

## Docker threat model

The runtime disables container networking, drops Linux capabilities, prevents
privilege escalation, applies memory/CPU/PID limits, and uses read-only container
root filesystems. Repository workspaces are bind-mounted read/write. The Docker
socket is mounted only into the local worker and must not be exposed to browser,
API, or untrusted clients. Ordinary containers are not perfect isolation:
kernel vulnerabilities, privileged socket access, and host resource abuse remain
possible. Stronger sandboxing requires rootless Docker or gVisor.
