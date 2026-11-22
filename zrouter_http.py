"""HTTP adapter for the OpenAI-compatible zrouter proxy."""

from __future__ import annotations

import hmac
import json
import logging
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from zrouter_contracts import MAX_REQUEST_BYTES, RouterError

log = logging.getLogger("nvrouter")


def _read_body(handler: BaseHTTPRequestHandler) -> tuple[int, dict[str, Any]]:
    """Read and parse the request body with a hard size cap."""
    try:
        n = int(handler.headers.get("Content-Length", 0))
    except (ValueError, TypeError):
        n = 0
    n = max(n, 0)
    if n > MAX_REQUEST_BYTES:
        return 413, {
            "error": {
                "message": "request entity too large",
                "type": "router_error",
                "code": 413,
            }
        }
    raw = handler.rfile.read(n) if n else b"{}"
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        return 400, {
            "error": {"message": "invalid JSON", "type": "router_error", "code": 400}
        }
    if not isinstance(body, dict):
        return 400, {
            "error": {
                "message": "request body must be a JSON object",
                "type": "router_error",
                "code": 400,
            }
        }
    return 200, body


def make_handler(router: Any, token: str | None, routes: dict[str, list[str]]):
    class H(BaseHTTPRequestHandler):
        server_version = "nvrouter/1.0"

        def log_message(self, fmt: str, *a: Any) -> None:
            log.info("%s - %s", self.address_string(), fmt % a)

        def _json(
            self, code: int, obj: Any, extra: dict[str, str] | None = None
        ) -> None:
            raw = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(raw)

        def _err(self, status: int, msg: str) -> None:
            self._json(
                status,
                {"error": {"message": msg, "type": "router_error", "code": status}},
            )

        def _authed(self) -> bool:
            if not token:
                return True
            provided = self.headers.get("Authorization", "")
            expected = f"Bearer {token}"
            if not hmac.compare_digest(provided, expected):
                self._err(401, "invalid router token")
                return False
            return True

        def do_GET(self) -> None:
            if not self._authed():
                return
            if self.path == "/health":
                return self._json(
                    200,
                    {
                        "ok": True,
                        "keys": [
                            {"key": a, "provider": b, "status": c, "ok": d, "429": e}
                            for a, b, c, d, e in router.key_status()
                        ],
                    },
                )
            try:
                if self.path.rstrip("/") == "/v1/models":
                    ids = ["auto"] + [f"free-{r}" for r in routes] + router.all_allowed()
                    return self._json(
                        200,
                        {
                            "object": "list",
                            "data": [
                                {
                                    "id": i,
                                    "object": "model",
                                    "owned_by": "nvidia-free-router",
                                }
                                for i in ids
                            ],
                        },
                    )
                if self.path == "/stats":
                    return self._json(
                        200, router.stats.snapshot() if router.stats else {}
                    )
            except RouterError as e:
                return self._err(e.status, e.message)
            self._err(404, "not found")

        def do_POST(self) -> None:
            if not self._authed():
                return
            code, body_or_err = _read_body(self)
            if code != 200:
                return self._json(code, body_or_err)
            body = body_or_err
            try:
                path = self.path.rstrip("/")
                if path == "/v1/chat/completions":
                    if body.get("stream"):
                        resp, m, _key = router.open_chat_stream(body)
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("X-Router-Model", m)
                        self.end_headers()
                        try:
                            for line in resp.iter_lines():
                                if line:
                                    self.wfile.write(line + b"\n\n")
                                    self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                        finally:
                            resp.close()
                        return
                    out = router.chat_json(body)
                    return self._json(
                        200,
                        out["json"],
                        {
                            "X-Router-Model": out["model"],
                            "X-Router-Key": out["key"],
                            "X-Router-Cache": str(out["cached"]).lower(),
                        },
                    )
                if path == "/v1/embeddings":
                    return self._json(200, router.embeddings(body))
                self._err(404, "not found")
            except RouterError as e:
                self._err(e.status, e.message)
            except Exception:  # pragma: no cover – safety net
                log.exception("unhandled")
                self._err(500, "internal server error")

    return H


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"}


def _require_token_for_public_bind(host: str, token: str | None) -> None:
    """Refuse to start an unauthenticated proxy on a non-loopback interface.

    Binding to 0.0.0.0 (or any LAN/external address) without ROUTER_TOKEN exposes
    the router and upstream keys to everyone on the network. Fail closed instead.
    """
    if token:
        return
    if host in _LOOPBACK_HOSTS:
        return
    log.error(
        "ROUTER_TOKEN is required when binding to %s; refusing to start an "
        "unauthenticated proxy on a non-loopback interface.",
        host,
    )
    sys.exit(1)


def serve(
    router: Any,
    host: str,
    port: int,
    token: str | None,
    routes: dict[str, list[str]],
) -> None:
    _require_token_for_public_bind(host, token)
    srv = ThreadingHTTPServer((host, port), make_handler(router, token, routes))
    srv.daemon_threads = True
    log.warning(
        "serving on http://%s:%d/v1  (auth %s, %d key(s))",
        host,
        port,
        "ON" if token else "off",
        len(router.keys),
    )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if router.stats:
            router.stats.flush()
