"""Replay: re-send a recorded (optionally edited) request into the application.

The request is dispatched *in process* through the whole ASGI stack of the app
(every middleware, routing, dependencies) - no port, TLS or worker routing
involved, and it works the same under uvicorn, gunicorn workers or tests.

Safety rules (enforced here, not only in the UI):
* disabled unless GLOWTRACE_REPLAY=1 / replay=True (development only);
* values still masked by redaction ([REDACTED], [CPF], [JWT]...) are refused:
  the originals were never stored, the user must provide them;
* the Glowtrace UI itself cannot be the target;
* the replayed request carries `X-Glowtrace-Replay: <original id>` so the app can
  skip side effects (also available as `glowtrace.is_replay()`).
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # pragma: no cover
    from .core import Glowtrace

METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
_MASK = re.compile(r"\[(REDACTED|CPF|CNPJ|CARD|JWT)\]")
_DROP_HEADERS = {"host", "content-length", "connection", "transfer-encoding", "accept-encoding", "keep-alive", "upgrade"}
MAX_BODY = 1_000_000
MAX_RESPONSE_PREVIEW = 64_000


class ReplayError(ValueError):
    def __init__(self, message: str, fields: Optional[list[str]] = None) -> None:
        super().__init__(message)
        self.fields = fields or []


def validate(core: "Glowtrace", spec: Any) -> dict:
    if not isinstance(spec, dict):
        raise ReplayError("especificação inválida")
    method = str(spec.get("method") or "").upper()
    if method not in METHODS:
        raise ReplayError(f"método inválido: {method or '(vazio)'}")
    path = str(spec.get("path") or "")
    if not path.startswith("/") or "://" in path:
        raise ReplayError("o path deve começar com '/'")
    if path == core.prefix or path.startswith(core.prefix + "/"):
        raise ReplayError("não é possível reenviar para a interface do Glowtrace")
    query = spec.get("query") or ""
    if isinstance(query, dict):
        from urllib.parse import urlencode

        query = urlencode([(k, v) for k, v in query.items()], doseq=True)
    query = str(query).lstrip("?")
    headers: dict[str, str] = {}
    masked: list[str] = []
    for k, v in (spec.get("headers") or {}).items():
        key = str(k).strip().lower()
        if not key or key in _DROP_HEADERS or key.startswith("x-glowtrace-"):
            continue
        val = str(v)
        if _MASK.search(val):
            masked.append(f"headers.{key}")
        headers[key] = val
    body = spec.get("body")
    if body is not None and not isinstance(body, str):
        body = json.dumps(body, ensure_ascii=False)
    if body is not None:
        if len(body.encode("utf-8")) > MAX_BODY:
            raise ReplayError("corpo maior que 1 MB")
        if _MASK.search(body):
            masked.append("body")
    if _MASK.search(query):
        masked.append("query")
    if masked:
        raise ReplayError(
            "há valores mascarados pela redação; informe os valores reais ou remova os campos antes de reenviar",
            masked,
        )
    edits = [str(e)[:120] for e in (spec.get("edits") or [])][:50]
    replay_of = spec.get("replay_of")
    return {
        "method": method,
        "path": path,
        "query": query,
        "headers": headers,
        "body": body,
        "edits": edits,
        "replay_of": str(replay_of)[:64] if replay_of else None,
    }


async def run(core: "Glowtrace", spec: dict, origin_scope: dict) -> dict:
    """Dispatch the request into the app and return status + new execution id."""
    rid = core.register_replay(spec["replay_of"] or "manual", spec["edits"])
    body = (spec["body"] or "").encode("utf-8")
    hdrs = [(k.encode("latin-1"), v.encode("latin-1", "replace")) for k, v in spec["headers"].items()]
    if body and not any(k == b"content-type" for k, _ in hdrs):
        hdrs.append((b"content-type", b"application/json"))
    hdrs += [
        (b"content-length", str(len(body)).encode()),
        (b"x-glowtrace-replay", (spec["replay_of"] or "manual").encode("latin-1")),
        (b"x-glowtrace-replay-id", rid.encode()),
        (b"x-glowtrace-trace", b"1"),
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": spec["method"],
        "scheme": origin_scope.get("scheme", "http"),
        "path": spec["path"],
        "raw_path": spec["path"].encode("utf-8"),
        "query_string": spec["query"].encode("latin-1", "replace"),
        "root_path": origin_scope.get("root_path", ""),
        "headers": hdrs,
        "client": ("127.0.0.1", 0),
        "server": origin_scope.get("server") or ("127.0.0.1", 80),
        "state": dict(origin_scope.get("state") or {}),  # lifespan state, as the server would pass it
        "extensions": {},
    }
    done = asyncio.Event()
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await done.wait()  # like a client that stays connected until the response ends
        return {"type": "http.disconnect"}

    resp: dict[str, Any] = {"status": None, "headers": [], "body": bytearray(), "size": 0}

    async def send(message):
        if message["type"] == "http.response.start":
            resp["status"] = message.get("status")
            resp["headers"] = message.get("headers") or []
        elif message["type"] == "http.response.body":
            chunk = message.get("body", b"") or b""
            resp["size"] += len(chunk)
            room = MAX_RESPONSE_PREVIEW - len(resp["body"])
            if room > 0:
                resp["body"] += chunk[:room]
            if not message.get("more_body", False):
                done.set()

    error = None
    try:
        await core.app(scope, receive, send)
    except Exception as exc:  # the app crashed: the execution is still recorded by the middleware
        error = f"{type(exc).__name__}: {exc}"
    finally:
        done.set()
        with core._lock:
            core._pending_replays.pop(rid, None)
    core.store.flush(2.0)
    recorded = core.store.get(rid) is not None
    return {
        "status": resp["status"] if resp["status"] is not None else 500,
        "execution_id": rid if recorded else None,
        "recorded": recorded,
        "error": error,
        "response_size": resp["size"],
        "response_preview": bytes(resp["body"]).decode("utf-8", "replace"),
    }
