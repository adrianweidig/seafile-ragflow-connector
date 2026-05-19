# Portainer Operations

## Basic Stack

Create a new Portainer stack and paste `docker-compose.portainer.yml`.

Set environment values from `stack.env.example`. At minimum configure:

- `SEAFILE_BASE_URL`
- `SEAFILE_ADMIN_TOKEN`
- `SEAFILE_SYNC_USER_TOKEN`
- `RAGFLOW_BASE_URL`
- `RAGFLOW_API_KEY`
- `POSTGRES_PASSWORD`
- `DATABASE_URL`

## Scaling Workers

Scale `connector-worker` in Portainer when RAGFlow and Seafile can handle additional
load. Parsing and embedding inside RAGFlow are usually the bottleneck, so increase
worker count conservatively.

## External Docker Networks

If Seafile or RAGFlow run in Docker, attach this stack to their existing network and
use internal service names for `SEAFILE_BASE_URL` and `RAGFLOW_BASE_URL`.

