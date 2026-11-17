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
