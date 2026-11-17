"""Replay / edit-and-resend of recorded requests."""
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

from conftest import frame_by_fn, get_execution

AUTH = {"Authorization": "Bearer ana.sig.x"}


def _loja(make_ez, **kw):
    from examples.loja.main import create_app

    app = create_app()
    ez = make_ez(app, **kw)
    return app, ez, TestClient(app, raise_server_exceptions=False)


def test_replay_is_disabled_by_default(make_ez):
    app, ez, c = _loja(make_ez)
    assert c.get("/_glowtrace/api/meta").json()["replay_enabled"] is False
    r = c.post("/_glowtrace/api/replay", json={"method": "GET", "path": "/relatorio"})
    assert r.status_code == 403 and "GLOWTRACE_REPLAY" in r.json()["detail"]


def test_replay_with_edited_body_creates_marked_execution(make_ez):
    app, ez, c = _loja(make_ez, replay=True)
    assert c.get("/_glowtrace/api/meta").json()["replay_enabled"] is True
    original = c.post("/pedidos", json={"cliente": "ana", "itens": [{"produto": "camiseta", "qtd": 4}]}, headers=AUTH)
    orig_id = original.headers["x-glowtrace-execution"]
    r = c.post(
        "/_glowtrace/api/replay",
        json={
            "replay_of": orig_id,
            "method": "POST",
            "path": "/pedidos",
            "headers": {"content-type": "application/json", "authorization": "Bearer bia.sig.y"},
            "body": {"cliente": "bia", "itens": [{"produto": "boné", "qtd": 1}], "cupom": "VIP"},
            "edits": ["body.cliente", "body.itens", "body.cupom"],
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == 200 and out["recorded"] is True and out["execution_id"]
    assert '"status":"pago"' in out["response_preview"].replace(" ", "")
    ex = c.get(f"/_glowtrace/api/executions/{out['execution_id']}").json()
    assert ex["mode"] == "replay" and ex["replay_of"] == orig_id
    assert ex["replay_edits"] == ["body.cliente", "body.itens", "body.cupom"]
    assert frame_by_fn(ex, "services.py::criar_pedido")["args"]["pedido"]["cliente"] == "bia"
    # the original is untouched and the list tells them apart
    assert get_execution(c, original)["mode"] == "recorded"
    modes = {e["id"]: e["mode"] for e in c.get("/_glowtrace/api/executions").json()["executions"]}
    assert modes[out["execution_id"]] == "replay" and modes[orig_id] == "recorded"


def test_app_sees_replay_header_and_is_replay(make_ez):
    from glowtrace import is_replay

    app = FastAPI()

    @app.get("/quem")
    def quem(x_glowtrace_replay: str | None = Header(default=None)):
        return {"is_replay": is_replay(), "header": x_glowtrace_replay}

    make_ez(app, replay=True)
    c = TestClient(app)
    normal = c.get("/quem")
    assert normal.json() == {"is_replay": False, "header": None}
    r = c.post("/_glowtrace/api/replay", json={"method": "GET", "path": "/quem", "replay_of": "abc123"})
    assert '"is_replay":true' in r.json()["response_preview"].replace(" ", "")
    assert '"header":"abc123"' in r.json()["response_preview"].replace(" ", "")


def test_masked_values_are_refused(make_ez):
    app, ez, c = _loja(make_ez, replay=True)
    r = c.post(
        "/_glowtrace/api/replay",
        json={"method": "POST", "path": "/pedidos", "headers": {"authorization": "Bearer [REDACTED]"},
              "body": {"cliente": "ana", "cpf": "[CPF]", "itens": []}},
    )
    assert r.status_code == 400
    assert set(r.json()["fields"]) == {"headers.authorization", "body"}


def test_invalid_targets_are_refused(make_ez):
    app, ez, c = _loja(make_ez, replay=True)
    assert c.post("/_glowtrace/api/replay", json={"method": "GET", "path": "/_glowtrace/api/meta"}).status_code == 400
    assert c.post("/_glowtrace/api/replay", json={"method": "TRACE", "path": "/relatorio"}).status_code == 400
    assert c.post("/_glowtrace/api/replay", json={"method": "GET", "path": "http://outro/relatorio"}).status_code == 400


def test_forged_replay_header_from_client_is_ignored(make_ez):
    app, ez, c = _loja(make_ez, replay=True)
    r = c.get("/relatorio", headers={"X-Glowtrace-Replay-Id": "deadbeef", "X-Glowtrace-Replay": "x"})
    ex = get_execution(c, r)
    assert ex["mode"] == "recorded" and ex["replay_of"] is None and ex["id"] != "deadbeef"


def test_replay_of_unhandled_error_is_still_recorded(make_ez):
    app, ez, c = _loja(make_ez, replay=True)
    r = c.post("/_glowtrace/api/replay", json={"method": "GET", "path": "/quebra", "replay_of": "x"}).json()
    assert r["status"] == 500 and r["recorded"] is True
    ex = c.get(f"/_glowtrace/api/executions/{r['execution_id']}").json()
    assert ex["error"]["type"] == "KeyError" and ex["mode"] == "replay"


def test_cross_site_requests_are_refused(make_ez):
    app, ez, c = _loja(make_ez, replay=True)
    spec = '{"method": "GET", "path": "/relatorio"}'
    r = c.post("/_glowtrace/api/replay", content=spec, headers={"content-type": "text/plain"})
    assert r.status_code == 415
    r = c.post("/_glowtrace/api/replay", json={"method": "GET", "path": "/relatorio"}, headers={"origin": "http://malicioso.example"})
    assert r.status_code == 403
    r = c.post("/_glowtrace/api/replay", json={"method": "GET", "path": "/relatorio"}, headers={"origin": "http://testserver"})
    assert r.status_code == 200
