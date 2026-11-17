"""End-to-end recording + overlay on the demo shop."""
import asyncio

import httpx
import pytest

from conftest import frame_by_fn, get_execution, overlay_of

AUTH = {"Authorization": "Bearer ana.sig.x"}


class remote_client:
    """Sync facade over httpx.ASGITransport with a non-loopback client address
    (TestClient(client=...) only exists in recent Starlette)."""

    def __init__(self, app):
        self.app = app
        self.cookies = httpx.Cookies()

    def get(self, url, headers=None):
        async def go():
            transport = httpx.ASGITransport(app=self.app, client=("10.0.0.5", 1234))
            async with httpx.AsyncClient(transport=transport, base_url="http://remote", cookies=self.cookies) as c:
                r = await c.get(url, headers=headers)
                self.cookies.update(c.cookies)
                return r

        return asyncio.run(go())


def _node(ez, frame, prefix):
    flow = ez.registry.flow(frame["fn"])
    return next(n.idx for n in flow.nodes if n.label.startswith(prefix))


def visited(ex, frame, node_idx):
    return overlay_of(ex, frame)["visits"].get(str(node_idx), 0)


def test_happy_path_records_call_tree(loja):
    app, ez, client = loja
    r = client.post(
        "/pedidos",
        json={"cliente": "ana", "itens": [{"produto": "camiseta", "qtd": 4}], "cupom": "VIP"},
        headers=AUTH,
    )
    assert r.status_code == 200
    ex = get_execution(client, r)
    assert ex["route_id"] == "POST /pedidos"
    assert ex["status"] == 200 and ex["error"] is None
    endpoint = frame_by_fn(ex, "main.py::criar_pedido")
    svc = frame_by_fn(ex, "services.py::criar_pedido")
    total = frame_by_fn(ex, "services.py::calcular_total")
    cupom = frame_by_fn(ex, "services.py::aplicar_cupom")
    assert svc["parent"] == endpoint["id"]
    assert total["parent"] == svc["id"]
    assert cupom["parent"] == total["id"]
    assert cupom["args"] == {"total": 239.6, "cupom": "VIP"}
    assert cupom["return"] == 179.7
    # branch taken: total > 200 -> true (frete grátis), else-branch not visited
    assert visited(ex, total, _node(ez, total, "pedido.avisos.append")) == 1
    assert visited(ex, total, _node(ez, total, "total += 15.0")) == 0
    # loop ran once (one item)
    assert visited(ex, total, _node(ez, total, "preco = PRECOS")) == 1
    # match: VIP case taken, PRIMEIRA body skipped
    assert visited(ex, cupom, _node(ez, cupom, "desconto = 0.25")) == 1
    assert visited(ex, cupom, _node(ez, cupom, "desconto = 0.1")) == 0
    # dependency (sync def, threadpool) and middleware are recorded too
    frame_by_fn(ex, "main.py::usuario_atual")
    frame_by_fn(ex, "main.py::cabecalhos_seguranca")
    # call node in parent frame identified
    assert overlay_of(ex, svc)["call_node"] == _node(ez, endpoint, "resultado = await services.criar_pedido")


def test_condition_values_are_captured(loja):
    app, ez, client = loja
    r = client.post("/pedidos", json={"cliente": "b", "itens": [{"produto": "boné", "qtd": 1}]}, headers=AUTH)
    ex = get_execution(client, r)
    total = frame_by_fn(ex, "services.py::calcular_total")
    if_idx = _node(ez, total, "if total > 200")
    pos = [i for i, p in enumerate(total["path"]) if p[0] == if_idx][0]
    before = [v for v in total["values"] if v[0] == pos and v[2] == "before"]
    assert before and before[0][1]["total"] == pytest.approx(39.9)
    assert visited(ex, total, _node(ez, total, "total += 15.0")) == 1


def test_loop_iterations_counted(loja):
    app, ez, client = loja
    r = client.post(
        "/pedidos",
        json={"cliente": "c", "itens": [{"produto": "camiseta"}, {"produto": "boné"}, {"produto": "camiseta"}]},
        headers=AUTH,
    )
    ex = get_execution(client, r)
    total = frame_by_fn(ex, "services.py::calcular_total")
    loop = _node(ez, total, "for item in pedido.itens")
    assert visited(ex, total, loop) == 4  # 3 iterations + exit check
    assert visited(ex, total, _node(ez, total, "preco = PRECOS")) == 3


def test_handled_exception_and_http_error(loja):
    app, ez, client = loja
    r = client.post("/pedidos", json={"cliente": "d", "itens": [{"produto": "caneca"}]}, headers=AUTH)
    assert r.status_code == 422
    ex = get_execution(client, r)
    svc = frame_by_fn(ex, "services.py::criar_pedido")
    assert svc["exception"]["type"] == "EstoqueInsuficiente"
    assert overlay_of(ex, svc)["error_node"] == _node(ez, svc, "raise EstoqueInsuficiente")
    endpoint = frame_by_fn(ex, "main.py::criar_pedido")
    assert endpoint["exception"]["type"] == "HTTPException"
    assert endpoint["exception"]["status_code"] == 422
    # except handler in the endpoint was entered
    assert visited(ex, endpoint, _node(ez, endpoint, "except EstoqueInsuficiente")) == 1
    assert ex["error"]["type"] == "HTTPException"


def test_unhandled_exception_500(loja):
    app, ez, client = loja
    r = client.get("/quebra")
    assert r.status_code == 500
    ez.store.flush()
    items = client.get("/_glowtrace/api/executions", params={"route": "GET /quebra"}).json()["executions"]
    assert items and items[0]["status"] == 500
    ex = client.get(f"/_glowtrace/api/executions/{items[0]['id']}").json()
    assert ex["error"]["type"] == "KeyError" and ex["error"]["escaped"] is True
    fr = frame_by_fn(ex, "main.py::quebra")
    assert overlay_of(ex, fr)["error_node"] == _node(ez, fr, "return dados['b']")


def test_dependency_rejects_without_token(loja):
    app, ez, client = loja
    r = client.post("/pedidos", json={"cliente": "e", "itens": []})
    assert r.status_code == 401
    ex = get_execution(client, r)
    dep = frame_by_fn(ex, "main.py::usuario_atual")
    assert dep["exception"]["detail"] == "sem token"
    assert not [f for f in ex["frames"] if f["fn"].endswith("services.py::criar_pedido")]


def test_redaction(loja):
    app, ez, client = loja
    r = client.post(
        "/pedidos",
        json={
            "cliente": "contato ana@example.com doc 529.982.247-25 cartao 4111 1111 1111 1111",
            "cpf": "52998224725",
            "senha_cartao": "1234",
            "itens": [{"produto": "boné"}],
        },
        headers=AUTH,
    )
    ex = get_execution(client, r)
    body = ex["request"]["body"]
    assert body["cpf"] == "[REDACTED]" and body["senha_cartao"] == "[REDACTED]"
    assert "529.982.247-25" not in body["cliente"] and "[CPF]" in body["cliente"]
    assert "[CARD]" in body["cliente"] and "a***@example.com" in body["cliente"]
    assert ex["request"]["headers"]["authorization"] == "[REDACTED]"
    import json

    blob = json.dumps(ex)
    assert "52998224725" not in blob and "4111 1111 1111 1111" not in blob


def test_concurrent_requests_do_not_mix(make_ez):
    from examples.loja.main import create_app

    app = create_app()
    ez = make_ez(app)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            reqs = [
                c.post("/pedidos", json={"cliente": f"cli{i}", "itens": [{"produto": "boné", "qtd": 1}] * (i % 3 + 1)}, headers=AUTH)
                for i in range(12)
            ]
            return await asyncio.gather(*reqs)

    responses = asyncio.run(run())
    ez.store.flush()
    for i, r in enumerate(responses):
        assert r.status_code == 200, r.text
        ex = ez.store.get(r.headers["x-glowtrace-execution"])
        svc = [f for f in ex["frames"] if f["fn"].endswith("services.py::criar_pedido")]
        assert len(svc) == 1
        assert svc[0]["args"]["pedido"]["cliente"] == f"cli{i}"
        cobrar = [f for f in ex["frames"] if f["fn"].endswith("::cobrar")]
        assert len(cobrar) == 1 and cobrar[0]["args"]["cliente"] == f"cli{i}"


def test_graph_mode_records_nothing(make_ez):
    from fastapi.testclient import TestClient

    from examples.loja.main import create_app

    app = create_app()
    ez = make_ez(app, mode="graph")
    c = TestClient(app)
    r = c.get("/relatorio")
    assert r.status_code == 200 and "x-glowtrace-execution" not in r.headers
    routes = c.get("/_glowtrace/api/routes").json()["routes"]
    assert {x["id"] for x in routes} >= {"POST /pedidos", "GET /pedidos/{pid}", "GET /relatorio", "GET /quebra"}


def test_routes_and_map(loja):
    app, ez, client = loja
    data = client.get("/_glowtrace/api/routes").json()
    post = next(r for r in data["routes"] if r["id"] == "POST /pedidos")
    assert post["handler"].endswith("main.py::criar_pedido")
    assert [d["fn"].split("::")[1] for d in post["dependencies"]] == ["usuario_atual"]
    assert data["middlewares"][0]["fn"].endswith("cabecalhos_seguranca")
    m = client.get("/_glowtrace/api/map").json()
    ids = {f["id"].split("::")[1] for f in m["functions"]}
    assert {"criar_pedido", "validar_itens", "calcular_total", "aplicar_cupom", "cobrar", "RepositorioPedidos.salvar"} <= ids


def test_remote_access_denied_without_token(make_ez):
    from fastapi.testclient import TestClient

    from examples.loja.main import create_app

    app = create_app()
    make_ez(app, mode="graph")
    c = remote_client(app)
    assert c.get("/_glowtrace/api/routes").status_code == 403


def test_token_access(make_ez):
    from fastapi.testclient import TestClient

    from examples.loja.main import create_app

    app = create_app()
    make_ez(app, mode="graph", token="s3cret")
    c = remote_client(app)
    assert c.get("/_glowtrace/api/routes").status_code == 403
    assert c.get("/_glowtrace/api/routes", headers={"x-glowtrace-token": "s3cret"}).status_code == 200
    r = c.get("/_glowtrace/?token=s3cret")
    assert r.status_code == 200
    assert c.get("/_glowtrace/api/routes").status_code == 200  # cookie set


def test_sampling_and_forced_header(make_ez):
    from fastapi.testclient import TestClient

    from examples.loja.main import create_app

    app = create_app()
    make_ez(app, sample_rate=0.0)
    c = TestClient(app)
    assert "x-glowtrace-execution" not in c.get("/relatorio").headers
    assert "x-glowtrace-execution" in c.get("/relatorio", headers={"x-glowtrace-trace": "1"}).headers


def test_sqlite_store(tmp_path, make_ez):
    from fastapi.testclient import TestClient

    from examples.loja.main import create_app

    app = create_app()
    ez = make_ez(app, store="sqlite", db_path=str(tmp_path / "ez.db"), max_executions=3)
    c = TestClient(app)
    ids = [c.get("/relatorio", params={"limite": i}).headers["x-glowtrace-execution"] for i in range(25)]
    ez.store.flush()
    listed = c.get("/_glowtrace/api/executions").json()["executions"]
    assert 1 <= len(listed) <= 23  # retention runs every 20 writes
    assert ez.store.get(ids[-1])["route_id"] == "GET /relatorio"


def test_included_router_with_prefix_and_router_dependency(make_ez):
    """FastAPI >= 0.16x stores included routers lazily (_IncludedRouter)."""
    from fastapi import APIRouter, Depends, FastAPI
    from fastapi.testclient import TestClient

    from examples.loja.main import usuario_atual

    router = APIRouter(dependencies=[Depends(usuario_atual)], tags=["pedidos"])

    @router.get("/itens/{pid}")
    def item(pid: int):
        if pid > 10:
            return {"grande": True}
        return {"grande": False}

    app = FastAPI()
    app.include_router(router, prefix="/v1")
    ez = make_ez(app)
    c = TestClient(app)
    routes = c.get("/_glowtrace/api/routes").json()["routes"]
    r = next(x for x in routes if x["path"] == "/v1/itens/{pid}")
    assert r["handler"].endswith("::test_included_router_with_prefix_and_router_dependency.<locals>.item")
    assert r["tags"] == ["pedidos"]
    assert [d["fn"].split("::")[1] for d in r["dependencies"]] == ["usuario_atual"]
    resp = c.get("/v1/itens/42", headers=AUTH)
    ex = get_execution(c, resp)
    assert ex["route_id"] == "GET /v1/itens/{pid}"
    fr = frame_by_fn(ex, ".item")
    assert fr["return"] == {"grande": True}


def test_return_await_in_middleware_is_not_an_error(loja):
    """`return await call_next(...)` must not be reported as StopIteration (settrace)."""
    app, ez, client = loja
    r = client.get("/relatorio")
    ex = get_execution(client, r)
    mw = frame_by_fn(ex, "main.py::cabecalhos_seguranca")
    assert "exception" not in mw, mw.get("exception")
    assert ex["error"] is None


def test_awaited_coroutine_chain_returns(make_ez):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    async def folha(x):
        return x + 1

    async def meio(x):
        return await folha(x)

    app = FastAPI()

    @app.get("/c")
    async def c():
        return {"v": await meio(1)}

    make_ez(app)
    cl = TestClient(app)
    ex = get_execution(cl, cl.get("/c"))
    assert ex["error"] is None
    for name in (".folha", ".meio", ".c"):
        f = frame_by_fn(ex, name)
        assert "exception" not in f, (name, f.get("exception"))
    assert frame_by_fn(ex, ".meio")["return"] == 2


def test_auto_instrumentation_many_apps_share_one_backend(tmp_path, monkeypatch):
    """glowtrace.auto attaches Glowtrace to every app; tracer and store are shared."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from glowtrace import auto
    from glowtrace.runtime import backends

    monkeypatch.setenv("GLOWTRACE_STORE", "sqlite")
    monkeypatch.setenv("GLOWTRACE_DB", str(tmp_path / "auto.db"))
    monkeypatch.setenv("GLOWTRACE_ROOTS", str(tmp_path.parent.parent) + __import__("os").pathsep + __import__("os").path.dirname(__file__))
    try:
        auto.install()
        apps = []
        for i in range(3):
            app = FastAPI()

            @app.get("/x")
            def x(i=i):
                if i % 2:
                    return {"odd": i}
                return {"even": i}

            apps.append(app)
        for app in apps:
            cl = TestClient(app)
            r = cl.get("/x")
            assert r.status_code == 200 and "x-glowtrace-execution" in r.headers
            # the /_glowtrace sub-app must not instrument itself (infinite recursion)
            assert cl.get("/_glowtrace/api/routes").status_code == 200
            app.state.glowtrace.store.flush()  # sqlite writes happen on a background thread
            assert cl.get(f"/_glowtrace/api/executions/{r.headers['x-glowtrace-execution']}").status_code == 200
        created = [a.state.glowtrace for a in apps]
        assert len({id(c.backend) for c in created}) == 1
        assert len({id(c.store) for c in created}) == 1
        created[0].store.flush()
        assert len(created[0].store.list()) == 3
    finally:
        auto.uninstall()
        for a in apps:
            ez = getattr(a.state, "glowtrace", None)
            if ez is not None:
                ez.close()
        assert backends._shared is None


def test_nested_app_defers_to_outer_recorder(make_ez):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    inner = FastAPI()

    @inner.get("/ping")
    def ping():
        return {"pong": True}

    outer = FastAPI()
    outer.mount("/sub", inner)
    make_ez(inner)
    make_ez(outer)
    c = TestClient(outer)
    r = c.get("/sub/ping")
    assert r.status_code == 200
    ex = get_execution(c, r)
    assert any(f["fn"].endswith(".ping") for f in ex["frames"])


def test_summary_tells_executions_apart_and_fail_filter(make_ez):
    from examples.loja.main import create_app
    from fastapi.testclient import TestClient

    app = create_app()
    make_ez(app)
    c = TestClient(app, raise_server_exceptions=False)
    auth = {"Authorization": "Bearer ana.sig.x"}
    c.post("/pedidos", json={"cliente": "ana", "itens": [{"produto": "camiseta", "qtd": 1}], "cupom": "VIP"}, headers=auth)
    c.post("/pedidos", json={"cliente": "bia", "itens": [{"produto": "caneca", "qtd": 2}]}, headers=auth)
    c.get("/quebra")
    rows = c.get("/_glowtrace/api/executions").json()["executions"]
    by_hint = {r["hint"]: r for r in rows if r["path"] == "/pedidos"}
    assert "cliente=ana · itens[1] · cupom=VIP" in by_hint
    refused = by_hint["cliente=bia · itens[1]"]
    assert refused["status"] == 422 and refused["detail"] == "sem estoque: caneca"
    fails = c.get("/_glowtrace/api/executions?status=fail").json()["executions"]
    assert {r["status"] for r in fails} == {422, 500}
    errors = c.get("/_glowtrace/api/executions?status=error").json()["executions"]
    assert 500 in {r["status"] for r in errors} and {r["id"] for r in errors} <= {r["id"] for r in fails}
