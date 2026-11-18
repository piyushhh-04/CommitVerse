FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/commitverse

COPY apps/hub-api/pyproject.toml apps/hub-api/README.md /opt/commitverse/apps/hub-api/
COPY packages/commitverse-core /opt/commitverse/packages/commitverse-core/
COPY apps/hub-api/src /opt/commitverse/apps/hub-api/src/
COPY apps/hub-api/migrations /opt/commitverse/apps/hub-api/migrations/
COPY apps/hub-api/alembic.ini /opt/commitverse/apps/hub-api/alembic.ini

RUN pip install --no-cache-dir -e /opt/commitverse/packages/commitverse-core \
    && pip install --no-cache-dir -e /opt/commitverse/apps/hub-api

WORKDIR /opt/commitverse/apps/hub-api

EXPOSE 8000

CMD ["commitverse-hub"]
