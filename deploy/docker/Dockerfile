ARG PYTHON_BASE_IMAGE=python:3.12.13-slim-trixie@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf
FROM ${PYTHON_BASE_IMAGE} AS runtime

ARG UV_VERSION=0.9.5

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

COPY pyproject.toml uv.lock README.md LICENSE alembic.ini /app/
COPY migrations /app/migrations
RUN pip install --root-user-action=ignore --no-cache-dir "uv==${UV_VERSION}" \
    && uv sync --frozen --no-dev --no-install-project

COPY src /app/src
COPY deploy/docker/entrypoint.sh /usr/local/bin/connector-entrypoint

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates gosu \
    && rm -rf /var/lib/apt/lists/*
RUN uv sync --frozen --no-dev
RUN chmod +x /usr/local/bin/connector-entrypoint

RUN useradd --create-home --uid 10001 connector \
    && mkdir -p /cache/tmp \
    && chown -R connector:connector /cache /home/connector

ENTRYPOINT ["connector-entrypoint"]
CMD ["controller"]
