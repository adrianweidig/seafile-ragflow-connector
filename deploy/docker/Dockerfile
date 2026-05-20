FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE /app/
COPY src /app/src
COPY deploy/docker/entrypoint.sh /usr/local/bin/connector-entrypoint

RUN pip install --root-user-action=ignore --no-cache-dir .
RUN chmod +x /usr/local/bin/connector-entrypoint

RUN useradd --create-home --uid 10001 connector \
    && mkdir -p /cache/tmp \
    && chown -R connector:connector /cache /home/connector
USER connector

ENTRYPOINT ["connector-entrypoint"]
CMD ["controller"]
