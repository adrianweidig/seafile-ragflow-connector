from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import socket
import struct
import sys
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4


class OBSBridgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class OBSWebSocketConfig:
    host: str
    port: int
    auth_secret: str | None
    timeout_seconds: float


class OBSWebSocketClient:
    def __init__(self, config: OBSWebSocketConfig) -> None:
        self.config = config

    def request(
        self,
        request_type: str,
        request_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with _OBSWebSocketSession(self.config) as session:
            return session.request(request_type, request_data or {})


class _OBSWebSocketSession:
    def __init__(self, config: OBSWebSocketConfig) -> None:
        self.config = config
        self.sock: socket.socket | None = None

    def __enter__(self) -> _OBSWebSocketSession:
        self.sock = socket.create_connection(
            (self.config.host, self.config.port),
            timeout=self.config.timeout_seconds,
        )
        self.sock.settimeout(self.config.timeout_seconds)
        self._handshake()
        self._identify()
        return self

    def __exit__(self, *_exc: object) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def request(self, request_type: str, request_data: dict[str, Any]) -> dict[str, Any]:
        request_id = str(uuid4())
        self._send_json(
            {
                "op": 6,
                "d": {
                    "requestType": request_type,
                    "requestId": request_id,
                    "requestData": request_data,
                },
            }
        )
        while True:
            message = self._recv_json()
            if int(message.get("op", -1)) != 7:
                continue
            data = message.get("d")
            if not isinstance(data, dict) or data.get("requestId") != request_id:
                continue
            status = data.get("requestStatus")
            if not isinstance(status, dict):
                raise OBSBridgeError(f"OBS response for {request_type} has no requestStatus")
            response = dict(data.get("responseData") or {})
            response["request_status"] = status
            if not bool(status.get("result")):
                code = status.get("code")
                comment = status.get("comment") or "request failed"
                raise OBSBridgeError(f"OBS request {request_type} failed ({code}): {comment}")
            return response

    def _handshake(self) -> None:
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            "GET / HTTP/1.1\r\n"
            f"Host: {self.config.host}:{self.config.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self._send_raw(request.encode("ascii"))
        response = self._read_until(b"\r\n\r\n", max_bytes=8192)
        first_line = response.splitlines()[0].decode("ascii", "replace")
        if " 101 " not in first_line:
            raise OBSBridgeError(f"OBS WebSocket handshake failed: {first_line}")

    def _identify(self) -> None:
        hello = self._recv_json()
        if int(hello.get("op", -1)) != 0:
            raise OBSBridgeError("OBS WebSocket did not send a Hello message")
        data = hello.get("d")
        if not isinstance(data, dict):
            raise OBSBridgeError("OBS WebSocket Hello message is malformed")
        identify: dict[str, Any] = {"rpcVersion": min(int(data.get("rpcVersion") or 1), 1)}
        authentication = data.get("authentication")
        if isinstance(authentication, dict):
            if not self.config.auth_secret:
                raise OBSBridgeError(
                    "OBS WebSocket requires authentication but no auth secret is set"
                )
            identify["authentication"] = _obs_auth_response(
                self.config.auth_secret,
                str(authentication.get("salt") or ""),
                str(authentication.get("challenge") or ""),
            )
        self._send_json({"op": 1, "d": identify})
        identified = self._recv_json()
        if int(identified.get("op", -1)) != 2:
            raise OBSBridgeError("OBS WebSocket identification failed")

    def _recv_json(self) -> dict[str, Any]:
        while True:
            opcode, payload = self._recv_frame()
            if opcode == 9:
                self._send_frame(payload, opcode=10)
                continue
            if opcode == 8:
                raise OBSBridgeError("OBS WebSocket closed the connection")
            if opcode not in {1, 2}:
                continue
            try:
                data = json.loads(payload.decode("utf-8"))
            except ValueError as exc:
                raise OBSBridgeError("OBS WebSocket returned invalid JSON") from exc
            if not isinstance(data, dict):
                raise OBSBridgeError("OBS WebSocket returned a non-object message")
            return data

    def _send_json(self, payload: dict[str, Any]) -> None:
        self._send_frame(json.dumps(payload, separators=(",", ":")).encode("utf-8"), opcode=1)

    def _recv_frame(self) -> tuple[int, bytes]:
        header = self._read_exact(2)
        first, second = header
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exact(8))[0]
        masked = bool(second & 0x80)
        mask = self._read_exact(4) if masked else b""
        payload = self._read_exact(length)
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def _send_frame(self, payload: bytes, *, opcode: int) -> None:
        first = 0x80 | opcode
        length = len(payload)
        mask = secrets.token_bytes(4)
        if length < 126:
            header = struct.pack("!BB", first, 0x80 | length)
        elif length <= 0xFFFF:
            header = struct.pack("!BBH", first, 0x80 | 126, length)
        else:
            header = struct.pack("!BBQ", first, 0x80 | 127, length)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self._send_raw(header + mask + masked)

    def _send_raw(self, data: bytes) -> None:
        if self.sock is None:
            raise OBSBridgeError("OBS WebSocket is not connected")
        self.sock.sendall(data)

    def _read_exact(self, length: int) -> bytes:
        if self.sock is None:
            raise OBSBridgeError("OBS WebSocket is not connected")
        chunks: list[bytes] = []
        remaining = length
        while remaining:
            chunk = self.sock.recv(remaining)
            if not chunk:
                raise OBSBridgeError("OBS WebSocket connection ended unexpectedly")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _read_until(self, marker: bytes, *, max_bytes: int) -> bytes:
        if self.sock is None:
            raise OBSBridgeError("OBS WebSocket is not connected")
        data = bytearray()
        while marker not in data:
            chunk = self.sock.recv(1)
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > max_bytes:
                raise OBSBridgeError("OBS WebSocket handshake response is too large")
        return bytes(data)


class OBSWebhookHandler(BaseHTTPRequestHandler):
    server: OBSWebhookServer

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write(f"obs-webhook-bridge {self.address_string()} {format % args}\n")

    def do_GET(self) -> None:
        if self.path.startswith("/status") or self.path.startswith("/health"):
            self._handle_status()
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        payload = self._json_body()
        if self.path.startswith("/start"):
            self._handle_start(payload)
        elif self.path.startswith("/stop"):
            self._handle_stop()
        elif self.path.startswith("/screenshot"):
            self._handle_screenshot(payload)
        elif self.path.startswith("/scene"):
            self._handle_scene(payload)
        elif self.path.startswith("/marker"):
            self._handle_marker(payload)
        else:
            self._send_json({"error": "not found"}, status=404)

    def _handle_status(self) -> None:
        self._send_json(self.server.obs_status())

    def _handle_start(self, payload: dict[str, Any]) -> None:
        scene_name = _string_or_none(payload.get("scene"))
        if scene_name:
            self.server.obs_request("SetCurrentProgramScene", {"sceneName": scene_name})
        status = self.server.obs_status()
        if not bool(status.get("recording")):
            self.server.obs_request("StartRecord")
            status = self.server.wait_for_recording(True)
        self._send_json(
            {
                "recording": bool(status.get("recording")),
                "status": status,
                "recording_name": _string_or_none(payload.get("recording_name")),
                "demo_id": _string_or_none(payload.get("demo_id")),
            }
        )

    def _handle_stop(self) -> None:
        status_before = self.server.obs_status()
        if bool(status_before.get("recording")):
            response = self.server.obs_request("StopRecord")
        else:
            response = {"already_stopped": True}
        status_after = self.server.wait_for_recording(False)
        output_path = _string_or_none(response.get("outputPath")) or _string_or_none(
            status_after.get("output_path")
        )
        self._send_json(
            {
                "recording": bool(status_after.get("recording")),
                "output_path": output_path,
                "recording_path": output_path,
                "status_before": status_before,
                "status_after": status_after,
                "response": response,
            }
        )

    def _handle_scene(self, payload: dict[str, Any]) -> None:
        scene_name = _string_or_none(payload.get("scene"))
        if not scene_name:
            self._send_json({"scene": None, "changed": False})
            return
        response = self.server.obs_request("SetCurrentProgramScene", {"sceneName": scene_name})
        self._send_json({"scene": scene_name, "changed": True, "response": response})

    def _handle_screenshot(self, payload: dict[str, Any]) -> None:
        source_name = (
            _string_or_none(payload.get("source_name"))
            or self.server.current_scene_name()
        )
        width = _int_or_none(payload.get("width")) or 1920
        height = _int_or_none(payload.get("height")) or 1080
        response = self.server.obs_request(
            "GetSourceScreenshot",
            {
                "sourceName": source_name,
                "imageFormat": "png",
                "imageWidth": width,
                "imageHeight": height,
            },
        )
        image_data = _string_or_none(response.get("imageData"))
        if not image_data:
            self._send_json(
                {
                    "source_name": source_name,
                    "written": False,
                    "error": "OBS did not return imageData",
                    "response": response,
                },
                status=502,
            )
            return
        output_path = _string_or_none(payload.get("output_path"))
        result: dict[str, Any] = {
            "source_name": source_name,
            "width": width,
            "height": height,
            "marker": _string_or_none(payload.get("marker")),
            "demo_id": _string_or_none(payload.get("demo_id")),
            "written": False,
        }
        if output_path:
            try:
                path = self.server.safe_screenshot_path(output_path)
            except OBSBridgeError as exc:
                self._send_json(
                    {
                        **result,
                        "path": output_path,
                        "error": str(exc),
                    },
                    status=400,
                )
                return
            raw = image_data.split(",", 1)[-1]
            data = base64.b64decode(raw)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            result.update(
                {
                    "written": True,
                    "path": str(path),
                    "size_bytes": path.stat().st_size,
                }
            )
        else:
            result["image_data_bytes"] = len(image_data)
        self._send_json(result)

    def _handle_marker(self, payload: dict[str, Any]) -> None:
        marker = _string_or_none(payload.get("marker")) or "recording marker"
        try:
            response = self.server.obs_request("CreateRecordChapter", {"chapterName": marker})
        except Exception as exc:
            self._send_json({"marker": marker, "created": False, "error": str(exc)})
            return
        self._send_json({"marker": marker, "created": True, "response": response})

    def _json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except ValueError:
            return {}
        return dict(payload) if isinstance(payload, dict) else {}

    def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class OBSWebhookServer(ThreadingHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        obs_config: OBSWebSocketConfig,
        *,
        screenshot_root: Path,
    ) -> None:
        super().__init__(address, OBSWebhookHandler)
        self.obs_client = OBSWebSocketClient(obs_config)
        self.screenshot_root = screenshot_root.resolve()

    def obs_request(
        self,
        request_type: str,
        request_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.obs_client.request(request_type, request_data or {})

    def obs_status(self) -> dict[str, Any]:
        response = self.obs_request("GetRecordStatus")
        output_path = _string_or_none(response.get("outputPath"))
        return {
            "recording": bool(response.get("outputActive")),
            "is_recording": bool(response.get("outputActive")),
            "output_paused": bool(response.get("outputPaused")),
            "output_path": output_path,
            "recording_path": output_path,
            "raw": response,
        }

    def current_scene_name(self) -> str:
        response = self.obs_request("GetCurrentProgramScene")
        scene_name = _string_or_none(response.get("currentProgramSceneName"))
        if not scene_name:
            raise OBSBridgeError("OBS did not return a current program scene name")
        return scene_name

    def safe_screenshot_path(self, output_path: str) -> Path:
        requested = Path(output_path)
        if not requested.is_absolute():
            requested = self.screenshot_root / requested
        resolved = requested.resolve()
        try:
            resolved.relative_to(self.screenshot_root)
        except ValueError as exc:
            raise OBSBridgeError(
                "screenshot output_path must stay below screenshot_root"
            ) from exc
        return resolved

    def wait_for_recording(self, expected: bool) -> dict[str, Any]:
        deadline = time.monotonic() + 10.0
        latest = self.obs_status()
        while bool(latest.get("recording")) != expected and time.monotonic() < deadline:
            time.sleep(0.25)
            latest = self.obs_status()
        return latest


def main() -> int:
    args = _parser().parse_args()
    obs_config = _obs_config_from_args(args)
    screenshot_root = args.screenshot_root.resolve()
    server = OBSWebhookServer(
        (args.host, args.port),
        obs_config,
        screenshot_root=screenshot_root,
    )
    print(
        json.dumps(
            {
                "status": "listening",
                "http": f"http://{args.host}:{args.port}",
                "obs_websocket": f"{obs_config.host}:{obs_config.port}",
                "auth_configured": bool(obs_config.auth_secret),
                "screenshot_root": str(screenshot_root),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Expose OBS WebSocket recording controls as local HTTP webhooks."
    )
    parser.add_argument("--host", default=os.environ.get("OBS_WEBHOOK_BRIDGE_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("OBS_WEBHOOK_BRIDGE_PORT", "9900")),
    )
    parser.add_argument("--obs-host", default=os.environ.get("OBS_WEBSOCKET_HOST", "127.0.0.1"))
    parser.add_argument("--obs-port", type=int, default=None)
    parser.add_argument(
        "--obs-password",
        dest="obs_auth_secret",
        default=os.environ.get("OBS_WEBSOCKET_PASSWORD"),
    )
    parser.add_argument(
        "--obs-config",
        type=Path,
        default=_default_obs_websocket_config_path(),
        help="Path to OBS obs-websocket config.json. Password is never printed.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(os.environ.get("OBS_WEBSOCKET_TIMEOUT_SECONDS", "20")),
    )
    parser.add_argument(
        "--screenshot-root",
        type=Path,
        default=Path(os.environ.get("OBS_WEBHOOK_SCREENSHOT_ROOT", os.getcwd())),
        help="Directory boundary for /screenshot output_path writes.",
    )
    return parser


def _obs_config_from_args(args: argparse.Namespace) -> OBSWebSocketConfig:
    config = _read_obs_websocket_config(args.obs_config)
    port = args.obs_port or _int_or_none(os.environ.get("OBS_WEBSOCKET_PORT"))
    return OBSWebSocketConfig(
        host=args.obs_host,
        port=port or int(config.get("server_port") or 4455),
        auth_secret=args.obs_auth_secret or _string_or_none(config.get("server_password")),
        timeout_seconds=args.timeout_seconds,
    )


def _read_obs_websocket_config(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise OBSBridgeError(f"OBS WebSocket config is not valid JSON: {path}") from exc
    return dict(payload) if isinstance(payload, dict) else {}


def _default_obs_websocket_config_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return Path("obs-websocket-config.json")
    return Path(appdata) / "obs-studio" / "plugin_config" / "obs-websocket" / "config.json"


def _obs_auth_response(auth_secret: str, salt: str, challenge: str) -> str:
    # OBS WebSocket v5 requires this SHA-256 challenge-response; this is not
    # credential storage or a verifier managed by this repository.
    secret = base64.b64encode(hashlib.sha256((auth_secret + salt).encode("utf-8")).digest())
    return base64.b64encode(hashlib.sha256(secret + challenge.encode("utf-8")).digest()).decode(
        "ascii"
    )


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
