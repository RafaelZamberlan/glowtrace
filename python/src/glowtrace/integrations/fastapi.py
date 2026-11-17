"""FastAPI / Starlette integration: route discovery and the recording middleware."""
from __future__ import annotations

import json
import random
import time
import uuid
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import parse_qsl

from ..runtime.capture import scrub_headers
from ..runtime.recorder import Recorder, current

if TYPE_CHECKING:  # pragma: no cover
    from ..core import Glowtrace


def _middleware_parts(m: Any) -> tuple[Any, dict]:
    cls = getattr(m, "cls", None)
    kwargs = getattr(m, "kwargs", None)
    if kwargs is None:
        kwargs = getattr(m, "options", None) or {}
    if cls is None and isinstance(m, (tuple, list)) and m:
        cls = m[0]
    return cls, dict(kwargs)


class FastAPIAdapter:
    def __init__(self, app: Any, core: "Glowtrace") -> None:
        self.app = app
        self.core = core
        self._routes: Optional[list[dict]] = None
        self._route_count = -1
        self._by_obj: dict[int, str] = {}
        self._by_endpoint: dict[int, list[str]] = {}
        self._middlewares: Optional[list[dict]] = None

    # -- discovery -------------------------------------------------------------
    def routes(self) -> list[dict]:
        if self._routes is not None and len(self.app.routes) == self._route_count:
            return self._routes
        reg = self.core.registry
        out: list[dict] = []
        self._by_obj.clear()
        self._by_endpoint.clear()
        seen_ids: set[str] = set()

        def walk(routes, prefix: str) -> None:
            for item in routes:
                # FastAPI >= 0.16x keeps included routers lazily (_IncludedRouter);
                # each "effective route context" carries the full path/endpoint/deps.
                contexts = getattr(item, "effective_route_contexts", None)
                if callable(contexts):
                    try:
                        for ctx in contexts():
                            visit(ctx.original_route, prefix + (ctx.path or ""), ctx)
                    except Exception:
                        pass
                    continue
                visit(item, prefix + (getattr(item, "path", "") or ""), None)

        def visit(r, path: str, ctx) -> None:
            src = ctx if ctx is not None else r
            cls = type(r).__name__
            if path.startswith(self.core.prefix):
                return
            endpoint = getattr(src, "endpoint", None) or getattr(r, "endpoint", None)
            if cls == "Mount":
                sub = getattr(r, "routes", None)
                if sub:
                    walk(sub, path)
                else:
                    rid = f"MOUNT {path}"
                    out.append({"id": rid, "kind": "mount", "methods": [], "path": path, "name": getattr(r, "name", None)})
                return
            methods = sorted(m for m in (getattr(src, "methods", None) or getattr(r, "methods", None) or []) if m != "HEAD")
            kind = "websocket" if "WebSocket" in cls else "http"
            if kind == "http" and not methods:
                methods = ["GET"]
            rid = f"{'|'.join(methods) or 'WS'} {path}"
            n = 2
            base = rid
            while rid in seen_ids:
                rid = f"{base} #{n}"
                n += 1
            seen_ids.add(rid)
            handler = reg.register_callable(endpoint) if endpoint is not None else None
            if handler is None and not getattr(src, "include_in_schema", True):
                seen_ids.discard(rid)
                return  # framework-internal routes (/docs, /openapi.json, /redoc...)
            deps: list[dict] = []
            dependant = getattr(src, "dependant", None) or getattr(r, "dependant", None)
            if dependant is not None:
                self._collect_deps(dependant, deps, set())
            flow = reg.flow(handler) if handler else None
            entry = {
                "id": rid,
                "kind": kind,
                "methods": methods,
                "path": path,
                "name": getattr(src, "name", None) or getattr(r, "name", None),
                "summary": getattr(src, "summary", None),
                "tags": [str(t) for t in (getattr(src, "tags", None) or [])],
                "handler": handler,
                "handler_desc": reg.describe_callable(endpoint) if endpoint is not None else None,
                "dependencies": deps,
                "file": flow.rel_file if flow else None,
                "line": flow.line if flow else None,
                "is_async": flow.is_async if flow else None,
            }
            out.append(entry)
            self._by_obj[id(r)] = rid
            if endpoint is not None:
                self._by_endpoint.setdefault(id(endpoint), []).append(rid)

        walk(self.app.routes, "")
        self._routes = out
        self._route_count = len(self.app.routes)
        return out

    def _collect_deps(self, dependant: Any, out: list[dict], seen: set) -> None:
        reg = self.core.registry
        for d in getattr(dependant, "dependencies", None) or []:
            self._collect_deps(d, out, seen)
            call = getattr(d, "call", None)
            if call is None or id(call) in seen:
                continue
            seen.add(id(call))
            fid = reg.register_callable(call)
            if fid is None:
                continue
            out.append({"fn": fid, "desc": reg.describe_callable(call)})

    def middlewares(self) -> list[dict]:
        if self._middlewares is not None:
            return self._middlewares
        reg = self.core.registry
        out = []
        for m in getattr(self.app, "user_middleware", []) or []:
            cls, kwargs = _middleware_parts(m)
            if cls is None:
                continue
            name = getattr(cls, "__name__", str(cls))
            fid = None
            dispatch = kwargs.get("dispatch")
            if dispatch is not None:
                fid = reg.register_callable(dispatch)
                name = getattr(dispatch, "__name__", name)
            else:
                for attr in ("dispatch", "__call__"):
                    fn = cls.__dict__.get(attr) if isinstance(cls, type) else None
                    if fn is not None:
                        fid = reg.register_callable(fn)
                        if fid:
                            break
            out.append({"name": name, "fn": fid, "kind": "user" if fid else "library"})
        self._middlewares = out
        return out

    def match(self, scope: dict) -> Optional[str]:
        self.routes()
        r = scope.get("route")
        if r is not None and id(r) in self._by_obj:
            return self._by_obj[id(r)]
        ep = scope.get("endpoint")
        if ep is not None:
            ids = self._by_endpoint.get(id(ep))
            if ids and len(ids) == 1:
                return ids[0]
        try:
            from starlette.routing import Match

            for r in self.app.routes:
                m, _ = r.matches(scope)
                if m == Match.FULL and id(r) in self._by_obj:
                    return self._by_obj[id(r)]
        except Exception:
            pass
        return None


# -----------------------------------------------------------------------------
# middleware


def _decode_body(raw: bytes, total: int, content_type: str, core: "Glowtrace") -> Any:
    if total == 0:
        return None
    cap = core.capturer
    ct = content_type.lower()
    truncated = total > len(raw)
    if "multipart/" in ct:
        return f"<multipart {total} bytes>"
    if "json" in ct and not truncated:
        try:
            return cap.capture(json.loads(raw.decode("utf-8")))
        except Exception:
            pass
    if "x-www-form-urlencoded" in ct and not truncated:
        try:
            return cap.capture(dict(parse_qsl(raw.decode("utf-8"), keep_blank_values=True)))
        except Exception:
            pass
    if ct.startswith("text/") or "json" in ct or "xml" in ct or "html" in ct:
        try:
            text = raw.decode("utf-8", "replace")
            return cap.scrub_text(text[:2000]) + (f"…(+{total - len(raw)} bytes)" if truncated else "")
        except Exception:
            pass
    return f"<{ct or 'binary'} {total} bytes>"


class GlowtraceMiddleware:
    """Outermost ASGI middleware: serves /_glowtrace and records traced requests."""

    def __init__(self, app: Any, core: "Glowtrace") -> None:
        self.app = app
        self.core = core

    async def __call__(self, scope, receive, send):
        core = self.core
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path: str = scope.get("path", "")
        if path == core.prefix or path.startswith(core.prefix + "/"):
            return await core.server(scope, receive, send)
        if current.get() is not None or not core.should_trace(scope):
            # an outer Glowtrace app (this one is mounted inside it) is already recording
            return await self.app(scope, receive, send)

        rec = Recorder(core.registry, core.capturer, core.limits)
        replay = core.claim_replay(scope)
        if replay is not None:
            rec.id = replay["id"]
            rec.replay_of = replay.get("replay_of")
            rec.replay_edits = list(replay.get("edits") or [])
        backend = core.backend
        if backend is not None:
            backend.begin()
        headers = scope.get("headers") or []
        hdict = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in headers}
        trace_id = _trace_id(hdict.get("traceparent"))
        max_body = core.max_body
        req_parts: list[bytes] = []
        req_state = {"size": 0, "total": 0}

        async def recv():
            msg = await receive()
            if msg.get("type") == "http.request":
                b = msg.get("body", b"") or b""
                req_state["total"] += len(b)
                room = max_body - req_state["size"]
                if room > 0 and b:
                    req_parts.append(b[:room])
                    req_state["size"] += min(room, len(b))
            return msg

        resp = {"status": None, "headers": [], "parts": [], "size": 0, "total": 0}

        async def snd(msg):
            t = msg.get("type")
            if t == "http.response.start":
                resp["status"] = msg.get("status")
                resp["headers"] = list(msg.get("headers") or [])
                if core.expose_header:
                    msg = dict(msg)
                    msg["headers"] = resp["headers"] + [(b"x-glowtrace-execution", rec.id.encode())]
            elif t == "http.response.body":
                b = msg.get("body", b"") or b""
                resp["total"] += len(b)
                room = max_body - resp["size"]
                if room > 0 and b:
                    resp["parts"].append(b[:room])
                    resp["size"] += min(room, len(b))
            await send(msg)

        token = current.set(rec)
        error: Optional[BaseException] = None
        try:
            await self.app(scope, recv, snd)
        except BaseException as exc:  # record and re-raise
            error = exc
            raise
        finally:
            current.reset(token)
            if backend is not None:
                backend.end()
            rec.close()
            try:
                core.finish(rec, scope, hdict, trace_id, req_parts, req_state, resp, error)
            except Exception:  # never break the app because of us
                core.log_internal_error()


def _trace_id(traceparent: Optional[str]) -> str:
    if traceparent:
        parts = traceparent.split("-")
        if len(parts) >= 4 and len(parts[1]) == 32:
            return parts[1]
    return uuid.uuid4().hex


def build_execution(core: "Glowtrace", rec: Recorder, scope: dict, hdict: dict, trace_id: str, req_parts, req_state, resp, error) -> dict:
    cap = core.capturer
    duration_ms = (time.perf_counter_ns() - rec.t0) / 1e6
    frames = rec.frames_json()
    route_id = core.adapter.match(scope)
    query = dict(parse_qsl((scope.get("query_string") or b"").decode("latin-1"), keep_blank_values=True))
    req_ct = hdict.get("content-type", "")
    resp_hdict = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in resp["headers"]}
    err = None
    if error is not None:
        error = _unwrap_group(error)
        err = {"type": type(error).__name__, "message": cap.scrub_text(str(error))[:500], "escaped": True}
    else:
        tops = [f for f in frames if f.get("parent") is None and f.get("exception")]
        if tops:
            e = tops[-1]["exception"]
            err = {"type": e.get("type"), "message": e.get("message"), "escaped": False}
            if e.get("status_code"):
                err["status_code"] = e["status_code"]
    for f in frames:
        if f.get("exception") and err is not None and "fn" not in err:
            # deepest origin: the frame whose children did not raise
            pass
    origin = _error_origin(frames)
    if err is not None and origin is not None:
        err["frame"] = origin
    status = resp["status"] if resp["status"] is not None else (500 if error is not None else None)
    request = {
        "headers": scrub_headers(scope.get("headers") or [], cap),
        "query": cap.capture(query) if query else {},
        "path_params": cap.capture(dict(scope.get("path_params") or {})),
        "body": _decode_body(b"".join(req_parts), req_state["total"], req_ct, core),
    }
    response = {
        "headers": scrub_headers(resp["headers"], cap),
        "body": _decode_body(b"".join(resp["parts"]), resp["total"], resp_hdict.get("content-type", ""), core),
    }
    return {
        "id": rec.id,
        "trace_id": trace_id,
        "started_at": rec.started_at,
        "method": scope.get("method"),
        "path": scope.get("path"),
        "route_id": route_id,
        "status": status,
        "duration_ms": round(duration_ms, 3),
        "error": err,
        "frame_count": len(frames),
        "truncated": rec.truncated,
        "mode": "replay" if rec.replay_of is not None else "recorded",
        "replay_of": rec.replay_of or None,
        "replay_edits": rec.replay_edits,
        "backend": core.backend.name if core.backend else None,
        "hint": request_hint(request),
        "detail": response_detail(response["body"], status),
        "request": request,
        "response": response,
        "frames": frames,
    }


def _short(v, n: int = 18) -> str:
    if isinstance(v, str):
        return v if len(v) <= n else v[: n - 1] + "…"
    if isinstance(v, list):
        return f"[{len(v)}]"
    if isinstance(v, dict):
        return "{…}"
    return str(v)


def request_hint(request: dict, limit: int = 70) -> Optional[str]:
    """A few already-redacted request values that tell executions apart in the list
    ("cliente=ana · itens[2] · cupom=VIP")."""
    parts: list[str] = []
    for src in (request.get("query"), request.get("body")):
        if not isinstance(src, dict):
            continue
        for k, v in src.items():
            if k == "__type__":
                continue
            parts.append(f"{k}[{len(v)}]" if isinstance(v, list) else f"{k}={_short(v)}")
            if len(parts) >= 4:
                break
    text = " · ".join(parts)
    return (text[: limit - 1] + "…" if len(text) > limit else text) or None


def response_detail(body, status) -> Optional[str]:
    """Why a request was refused (4xx/5xx), from the usual {"detail": ...} body."""
    if not status or status < 400 or not isinstance(body, dict) or "detail" not in body:
        return None
    d = body["detail"]
    if isinstance(d, list) and d and isinstance(d[0], dict):  # FastAPI validation errors
        loc = ".".join(str(x) for x in d[0].get("loc") or [])
        msg = str(d[0].get("msg") or "")
        more = f" (+{len(d) - 1})" if len(d) > 1 else ""
        return f"{loc}: {msg}{more}"[:140]
    return str(d)[:140] if d is not None else None


def _unwrap_group(exc: BaseException) -> BaseException:
    """anyio task groups (old Starlette BaseHTTPMiddleware) wrap the real error in an
    ExceptionGroup; report the single inner exception instead."""
    for _ in range(10):
        inner = getattr(exc, "exceptions", None)
        if isinstance(inner, (list, tuple)) and len(inner) == 1 and isinstance(inner[0], BaseException):
            exc = inner[0]
        else:
            break
    return exc


def _error_origin(frames: list[dict]) -> Optional[int]:
    """Frame id where the exception was first raised (deepest raising frame)."""
    raising = [f for f in frames if f.get("exception")]
    if not raising:
        return None
    ids = {f["id"] for f in raising}
    for f in reversed(raising):
        # a frame is the origin if none of its children raised
        if not any(c.get("parent") == f["id"] and c["id"] in ids for c in raising):
            return f["id"]
    return raising[-1]["id"]


def should_sample(rate: float) -> bool:
    return rate >= 1.0 or random.random() < rate
