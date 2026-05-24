from __future__ import annotations

import argparse
import json
import ssl
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse


class Handler(BaseHTTPRequestHandler):
    service_name = "tls-mock"

    def do_GET(self) -> None:  # noqa: N802
        payload: dict[str, Any]
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/v1/datasets":
            name = (query.get("name") or [""])[0]
            payload = {"code": 0, "data": {"datasets": _datasets_for_name(name)}}
        elif parsed.path.startswith("/api/v1/datasets/") and parsed.path.endswith("/documents"):
            payload = {"code": 0, "data": {"docs": []}}
        elif parsed.path.startswith("/api/v1/datasets/"):
            dataset_id = parsed.path.split("/")[4]
            payload = {"code": 0, "data": _dataset(dataset_id, dataset_id)}
        elif self.path.startswith("/api/v2.1/admin/libraries/"):
            payload = {
                "repos": [
                    {
                        "id": "repo-1",
                        "name": "TLS Demo",
                        "owner_email": "tls-demo@example.local",
                        "encrypted": False,
                        "virtual": False,
                        "head_commit_id": "tls-demo-head",
                    }
                ]
            }
        elif parsed.path.startswith("/api2/repos/") and parsed.path.endswith("/dir/"):
            payload = []
        elif parsed.path.startswith("/api2/repos/") and parsed.path.endswith("/file/"):
            payload = {"url": f"https://{self.headers.get('Host', '127.0.0.1')}/download/demo.txt"}
        elif parsed.path == "/download/demo.txt":
            self._send_bytes(b"TLS demo file\n", content_type="text/plain")
            return
        elif self.path.startswith("/api/health") or self.path == "/":
            payload = {"status": "ok", "service": self.service_name}
        else:
            payload = {"status": "ok", "service": self.service_name, "path": self.path}
        self._send_json(payload)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        body = self.rfile.read(int(self.headers.get("Content-Length") or "0"))
        try:
            request_payload = json.loads(body.decode() or "{}")
        except ValueError:
            request_payload = {}
        if parsed.path == "/api/v1/datasets":
            name = str(request_payload.get("name") or "mock-dataset")
            self._send_json({"code": 0, "data": _dataset(f"dataset-{_slug(name)}", name)})
            return
        if parsed.path.endswith("/chunks"):
            self._send_json({"code": 0, "data": {"status": "ok"}})
            return
        if parsed.path.endswith("/documents"):
            self._send_json({"code": 0, "data": {"id": "doc-demo", "name": "demo.txt"}})
            return
        self._send_json({"code": 0, "data": {"status": "ok"}})

    def do_DELETE(self) -> None:  # noqa: N802
        self._send_json({"code": 0, "data": {"status": "ok"}})

    def do_HEAD(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.OK)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.service_name}: {format % args}", flush=True)

    def _send_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self._send_bytes(body, content_type="application/json")

    def _send_bytes(self, body: bytes, *, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    args = parser.parse_args()

    Handler.service_name = args.name
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)  # nosec B104
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(args.cert, args.key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print(f"{args.name} listening on https://0.0.0.0:{args.port}", flush=True)
    server.serve_forever()


def _datasets_for_name(name: str) -> list[dict[str, Any]]:
    if not name:
        return [_dataset("template-dataset", "connector_template")]
    return [_dataset("template-dataset", name)] if name == "connector_template" else [
        _dataset(f"dataset-{_slug(name)}", name)
    ]


def _dataset(dataset_id: str, name: str) -> dict[str, Any]:
    return {
        "id": dataset_id,
        "name": name,
        "description": "TLS mock dataset",
        "embedding_model": "mock@local",
        "chunk_method": "naive",
        "parser_config": {},
        "permission": "me",
    }


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in value.lower()).strip("-") or "dataset"


if __name__ == "__main__":
    main()
