from dataclasses import dataclass

from glowtrace.runtime.capture import Capturer, CaptureConfig


def test_sensitive_keys():
    c = Capturer()
    for k in ("password", "Senha", "access_token", "refreshToken", "Authorization", "client_secret", "cpf", "CNPJ", "x-api-key", "cvv", "pin"):
        assert c.sensitive_key(k), k
    for k in ("produto", "shipping", "opinion", "cliente", "total", "spinner"):
        assert not c.sensitive_key(k), k


def test_value_patterns():
    c = Capturer()
    assert c.scrub_text("cpf 529.982.247-25") == "cpf [CPF]"
    assert c.scrub_text("cpf invalido 111.111.111-11") == "cpf invalido 111.111.111-11"
    assert c.scrub_text("cnpj 11.222.333/0001-81") == "cnpj [CNPJ]"
    assert c.scrub_text("card 4111-1111-1111-1111") == "card [CARD]"
    assert "[JWT]" in c.scrub_text("tok eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abc")
    assert c.scrub_text("Bearer abcdefghijkl") == "Bearer [REDACTED]"


def test_limits_and_no_repr_side_effects():
    calls = []

    class Lazy:
        def __init__(self):
            self.id = 1

        def __repr__(self):  # must never be called
            calls.append(1)
            return "boom"

        @property
        def heavy(self):
            calls.append(2)
            return 1

    c = Capturer(CaptureConfig(max_items=3, max_str=5))
    out = c.capture({"obj": Lazy(), "lst": list(range(10)), "s": "abcdefghij"})
    assert calls == []
    assert out["obj"] == {"__type__": "Lazy", "id": 1}
    assert out["lst"][-1] == "…(+7)"
    assert out["s"].startswith("abcde…")


def test_dataclass_and_nested_redaction():
    @dataclass
    class User:
        nome: str
        senha: str

    c = Capturer()
    assert c.capture(User("ana", "x")) == {"__type__": "User", "nome": "ana", "senha": "[REDACTED]"}


def test_deep_nesting_is_opened_and_cycles_stop():
    from glowtrace.runtime.capture import Capturer, CaptureConfig

    cap = Capturer(CaptureConfig())
    body = {"instructions": [{"metadata": {"options": {"itens": [{"id": 1, "label": "Saldo"}]}}}]}
    assert cap.capture(body) == body  # 6 levels: nothing collapsed into "<dict>"

    class No:
        def __init__(self, nome, pai=None):
            self.nome, self.pai, self.filhos = nome, pai, []

    pai = No("pai")
    pai.filhos.append(No("filho", pai))
    out = cap.capture(pai)
    assert out["filhos"][0]["pai"] == "<ciclo No>"
    assert out["filhos"][0]["nome"] == "filho"


def test_capture_limits_are_configurable(make_ez, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from glowtrace.runtime.capture import CaptureConfig

    deep = {"a": {"b": {"c": {"d": "fundo"}}}}

    def app_with(**kw):
        app = FastAPI()

        @app.post("/eco")
        def eco(body: dict):
            return body

        ez = make_ez(app, **kw)
        return TestClient(app), ez

    monkeypatch.setenv("GLOWTRACE_MAX_DEPTH", "2")
    monkeypatch.setenv("GLOWTRACE_MAX_ITEMS", "nao-numero")  # ignored, keeps the default
    c, ez = app_with()
    meta = c.get("/_glowtrace/api/meta").json()["capture"]
    assert meta["max_depth"] == 2 and meta["max_items"] == 25
    assert ez.capturer.capture(deep) == {"a": {"b": "<dict>"}}

    monkeypatch.setenv("GLOWTRACE_MAX_DEPTH", "500")  # clamped
    c, ez = app_with()
    assert c.get("/_glowtrace/api/meta").json()["capture"]["max_depth"] == 200

    monkeypatch.delenv("GLOWTRACE_MAX_DEPTH")
    monkeypatch.delenv("GLOWTRACE_MAX_ITEMS")
    c, ez = app_with(capture=CaptureConfig(max_depth=3, max_items=2))
    assert ez.capturer.capture(deep) == {"a": {"b": {"c": "<dict>"}}}
    assert ez.capturer.capture([1, 2, 3, 4]) == [1, 2, "…(+2)"]


def test_common_data_types_are_readable():
    import collections
    import enum
    import io
    import pathlib
    import typing

    import httpx
    import starlette.datastructures as sd
    from starlette.responses import JSONResponse, RedirectResponse, StreamingResponse

    from glowtrace.runtime.capture import Capturer, CaptureConfig

    cap = Capturer(CaptureConfig()).capture

    class Nivel(enum.IntEnum):
        A = 1

    class Ponto(typing.NamedTuple):
        x: int
        y: int

    assert cap(Nivel.A) == "Nivel.A"
    assert cap(Ponto(1, 2)) == {"x": 1, "y": 2}
    assert cap(pathlib.PurePosixPath("a/b")) == "a/b"
    assert cap(collections.deque([1, 2])) == [1, 2]
    assert cap(JSONResponse({"ok": True}, status_code=201)) == {
        "__type__": "JSONResponse", "status_code": 201, "media_type": "application/json", "body": {"ok": True}}
    assert cap(RedirectResponse("/novo"))["location"] == "/novo"
    assert cap(StreamingResponse(iter([b"x"])))["body"] == "<stream: não lido>"
    assert cap(httpx.Response(200, json={"token": "abc", "n": 1}))["body"] == {"token": "[REDACTED]", "n": 1}
    assert cap(sd.QueryParams("a=1&a=2&b=3")) == {"a": ["1", "2"], "b": "3"}
    assert cap(sd.Headers({"authorization": "Bearer x.y.z", "x-id": "1"})) == {"authorization": "[REDACTED]", "x-id": "1"}
    up = cap(sd.UploadFile(io.BytesIO(b"abc"), filename="f.png", size=3, headers=sd.Headers({"content-type": "image/png"})))
    assert up == {"__type__": "UploadFile", "filename": "f.png", "size": 3, "content_type": "image/png"}

    def gen():
        yield 1

    assert cap(gen()).startswith("<generator")  # never consumed


def test_sqlalchemy_rows_and_numpy_previews():
    import pytest

    from glowtrace.runtime.capture import Capturer, CaptureConfig

    cap = Capturer(CaptureConfig()).capture
    try:
        import sqlalchemy as sa
    except ImportError:
        sa = None
    if sa is not None:
        eng = sa.create_engine("sqlite://")
        with eng.connect() as c:
            row = c.execute(sa.text("select 1 as id, 'ABC' as placa")).first()
            assert cap(row) == {"id": 1, "placa": "ABC"}
            assert cap(c.execute(sa.text("select 2 as id")).mappings().first()) == {"id": 2}
    try:
        import numpy as np
    except ImportError:
        if sa is None:
            pytest.skip("sqlalchemy e numpy não instalados")
        return
    assert cap(np.int64(5)) == 5
    assert cap(np.array([1, 2]))["valores"] == [1, 2]
