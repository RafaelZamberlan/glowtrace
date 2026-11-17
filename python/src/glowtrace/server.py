"""The /_glowtrace sub-application: JSON API + bundled UI.

Access control (secure by default):
* if a token is configured (``GLOWTRACE_TOKEN`` / ``token=``) every request must
  carry it (``X-Glowtrace-Token`` header, ``?token=`` once -> cookie);
* otherwise only loopback clients are allowed unless ``allow_remote=True``;
* an ``auth(scope) -> bool`` callback can replace both rules.
"""
from __future__ import annotations

import hmac
import os
import platform
import sys
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from . import __version__
from .overlay import overlay_execution

if TYPE_CHECKING:  # pragma: no cover
    from .core import Glowtrace

UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ui")
_LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}

_FALLBACK_HTML = """<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<title>Glowtrace</title><body style="font-family:system-ui;padding:2rem;max-width:720px">
<h1>Glowtrace</h1><p>A interface não foi encontrada neste pacote (rode <code>npm run build</code> em <code>ui/</code>).</p>
<p>API JSON: <a href="api/routes">api/routes</a> · <a href="api/executions">api/executions</a> · <a href="api/map">api/map</a></p>
</body></html>"""


def build_server(core: "Glowtrace") -> Any:
    p = core.prefix

    def allowed(request: Request) -> tuple[bool, bool]:
        """(allowed, set_cookie)"""
        if core.auth is not None:
            try:
                return bool(core.auth(request.scope)), False
            except Exception:
                return False, False
        if core.token:
            supplied = (
                request.headers.get("x-glowtrace-token")
                or request.cookies.get("glowtrace_token")
                or request.query_params.get("token")
            )
            ok = bool(supplied) and hmac.compare_digest(str(supplied), str(core.token))
            return ok, ok and request.query_params.get("token") is not None
        host = request.client.host if request.client else None
        return (core.allow_remote or host in _LOOPBACK), False

    def guard(fn):
        async def wrapper(request: Request) -> Response:
            ok, set_cookie = allowed(request)
            if not ok:
                return JSONResponse(
                    {"detail": "Glowtrace: acesso negado. Use GLOWTRACE_TOKEN ou acesse via localhost."},
                    status_code=403,
                )
            resp = await fn(request)
            if set_cookie:
                resp.set_cookie("glowtrace_token", str(core.token), httponly=True, samesite="strict", path=p)
            resp.headers["cache-control"] = "no-store"
            resp.headers["x-content-type-options"] = "nosniff"
            return resp

        return wrapper

    async def index(request: Request) -> Response:
        path = os.path.join(UI_DIR, "index.html")
        if os.path.exists(path):
            return FileResponse(path, media_type="text/html")
        return HTMLResponse(_FALLBACK_HTML)

    async def to_index(request: Request) -> Response:
        q = ("?" + request.url.query) if request.url.query else ""
        return RedirectResponse(p + "/" + q)

    async def asset(request: Request) -> Response:
        rel = request.path_params["path"]
        full = os.path.normpath(os.path.join(UI_DIR, "assets", rel))
        if not full.startswith(os.path.join(UI_DIR, "assets")) or not os.path.isfile(full):
            return Response(status_code=404)
        return FileResponse(full)

    async def meta(request: Request) -> Response:
        routes = core.adapter.routes()
        return JSONResponse(
            {
                "title": core.title,
                "version": __version__,
                "mode": core.mode,
                "backend": core.backend.name if core.backend else None,
                "python": platform.python_version(),
                "runtime": f"python {platform.python_version()}",
                "platform": sys.platform,
                "prefix": p,
                "sample_rate": core.sample_rate,
                "route_count": len(routes),
                "internal_errors": core.internal_errors,
                "replay_enabled": core.replay_enabled,
                "capture": {
                    "max_depth": core.capturer.cfg.max_depth,
                    "max_items": core.capturer.cfg.max_items,
                    "max_values": core.capturer.cfg.budget,
                    "max_str": core.capturer.cfg.max_str,
                },
            }
        )

    async def routes(request: Request) -> Response:
        return JSONResponse({"routes": core.adapter.routes(), "middlewares": core.adapter.middlewares()})

    async def function(request: Request) -> Response:
        fid = request.query_params.get("id", "")
        flow = core.registry.flow(fid)
        if flow is None:
            return JSONResponse({"detail": "função não encontrada"}, status_code=404)
        data = flow.to_json()
        data["observed_calls"] = sorted({t for (s, t) in core.observed_edges if s == fid})
        return JSONResponse(data)

    async def api_map(request: Request) -> Response:
        rts = core.adapter.routes()
        mws = core.adapter.middlewares()
        roots = [r["handler"] for r in rts if r.get("handler")]
        roots += [d["fn"] for r in rts for d in r.get("dependencies", [])]
        roots += [m["fn"] for m in mws if m.get("fn")]
        fids = core.registry.reachable(roots)
        fid_set = set(fids)
        functions = []
        edges: dict[tuple[str, str], dict] = {}
        for fid in fids:
            f = core.registry.flow(fid)
            if f is None:
                continue
            ext = sorted({c.lib for n in f.nodes for c in n.calls if c.kind == "external" and c.lib})
            functions.append(
                {
                    "id": fid,
                    "qualname": f.qualname,
                    "file": f.rel_file,
                    "line": f.line,
                    "is_async": f.is_async,
                    "nodes": len(f.nodes),
                    "branches": sum(1 for n in f.nodes if n.kind in ("if", "loop", "match", "try")),
                    "external": ext,
                }
            )
            for n in f.nodes:
                for c in n.calls:
                    if c.kind == "user" and c.target and c.target in fid_set:
                        edges.setdefault((fid, c.target), {"source": fid, "target": c.target, "static": True, "observed": 0})
        for (s, t), count in list(core.observed_edges.items()):
            e = edges.get((s, t))
            if e is None:
                edges[(s, t)] = {"source": s, "target": t, "static": False, "observed": count}
                for x in (s, t):
                    if x not in fid_set:
                        f = core.registry.flow(x)
                        if f is not None:
                            fid_set.add(x)
                            functions.append({"id": x, "qualname": f.qualname, "file": f.rel_file, "line": f.line, "is_async": f.is_async, "nodes": len(f.nodes), "branches": 0, "external": [], "observed_only": True})
            else:
                e["observed"] = count
        return JSONResponse({"routes": rts, "middlewares": mws, "functions": functions, "edges": list(edges.values())})

    async def executions(request: Request) -> Response:
        if request.method == "DELETE":
            n = core.store.clear()
            return JSONResponse({"deleted": n})
        q = request.query_params
        try:
            limit = max(1, min(int(q.get("limit", "100")), 1000))
        except ValueError:
            limit = 100
        items = core.store.list(route_id=q.get("route") or None, limit=limit, status=q.get("status") or None)
        return JSONResponse({"executions": items})

    async def execution(request: Request) -> Response:
        ex = core.store.get(request.path_params["id"])
        if ex is None:
            return JSONResponse({"detail": "execução não encontrada"}, status_code=404)
        ex = dict(ex)
        ex["overlay"] = overlay_execution(ex, core.registry)
        return JSONResponse(ex)

    async def replay(request: Request) -> Response:
        from . import replay as rp

        if not core.replay_enabled:
            return JSONResponse(
                {"detail": "Replay desabilitado. Ative com GLOWTRACE_REPLAY=1 (somente em desenvolvimento)."},
                status_code=403,
            )
        # cross-site protection: a page on another origin can only send "simple" requests
        # (text/plain forms, no custom headers) without a CORS preflight, which we never grant
        if "application/json" not in request.headers.get("content-type", ""):
            return JSONResponse({"detail": "use Content-Type: application/json"}, status_code=415)
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host", ""):
            return JSONResponse({"detail": "origem não permitida"}, status_code=403)
        try:
            spec = rp.validate(core, await request.json())
        except rp.ReplayError as exc:
            return JSONResponse({"detail": str(exc), "fields": exc.fields}, status_code=400)
        except ValueError:
            return JSONResponse({"detail": "JSON inválido"}, status_code=400)
        return JSONResponse(await rp.run(core, spec, request.scope))

    app = Starlette(
        routes=[
            Route(p, guard(to_index)),
            Route(p + "/", guard(index)),
            Route(p + "/assets/{path:path}", guard(asset)),
            Route(p + "/api/meta", guard(meta)),
            Route(p + "/api/routes", guard(routes)),
            Route(p + "/api/function", guard(function)),
            Route(p + "/api/map", guard(api_map)),
            Route(p + "/api/executions", guard(executions), methods=["GET", "DELETE"]),
            Route(p + "/api/executions/{id}", guard(execution)),
            Route(p + "/api/replay", guard(replay), methods=["POST"]),
        ]
    )
    app._glowtrace_internal = True  # type: ignore[attr-defined]  # never auto-instrument ourselves
    return app
