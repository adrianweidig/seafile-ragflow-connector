from __future__ import annotations

import argparse
import json
import ssl
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class Handler(BaseHTTPRequestHandler):
    service_name = "tls-mock"

    def do_GET(self) -> None:  # noqa: N802
        payload: dict[str, Any]
        if self.path.startswith("/api/v1/datasets"):
            payload = {"code": 0, "data": {"datasets": [{"name": "connector_template"}]}}
        elif self.path.startswith("/api/v2.1/admin/libraries/"):
            payload = {"repos": [{"id": "repo-1", "name": "TLS Demo"}]}
        elif self.path.startswith("/api/health") or self.path == "/":
            payload = {"status": "ok", "service": self.service_name}
        else:
            payload = {"status": "ok", "service": self.service_name, "path": self.path}
        self._send_json(payload)

    def do_HEAD(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.OK)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.service_name}: {format % args}", flush=True)

    def _send_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
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
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(args.cert, args.key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print(f"{args.name} listening on https://0.0.0.0:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
