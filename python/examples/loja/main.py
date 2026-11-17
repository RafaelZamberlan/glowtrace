"""Demo shop API used by the tests and the README.

Run:  uvicorn examples.loja.app:app --reload   (from the python/ folder)
Open: http://127.0.0.1:8000/_easyapi/
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from . import services
from .services import EstoqueInsuficiente, Pedido


class Item(BaseModel):
    produto: str
    qtd: int = 1


class NovoPedido(BaseModel):
    cliente: str
    cpf: str | None = None
    senha_cartao: str | None = None
    itens: list[Item]
    cupom: str | None = None


def _dump(model) -> dict:
    """pydantic v2 (model_dump) and v1 (dict) compatible."""
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def create_app() -> FastAPI:
    """Build the demo app *without* EasyAPI (tests install it themselves)."""
    app = FastAPI(title="Loja Demo")
    _register(app)
    return app


def usuario_atual(authorization: str | None = Header(default=None)) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="sem token")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="formato inválido")
    return authorization.removeprefix("Bearer ").split(".")[0] or "anon"


async def cabecalhos_seguranca(request: Request, call_next):
    if request.url.path.startswith("/bloqueado"):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": "bloqueado"}, status_code=403)
    response = await call_next(request)
    response.headers["x-frame-options"] = "DENY"
    return response


async def criar_pedido(body: NovoPedido, usuario: str = Depends(usuario_atual)):
    pedido = Pedido(cliente=body.cliente, itens=[_dump(i) for i in body.itens], cupom=body.cupom)
    try:
        resultado = await services.criar_pedido(pedido)
    except EstoqueInsuficiente as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return resultado


def obter_pedido(pid: int):
    pedido = services.repo.buscar(pid)
    if pedido is None:
        raise HTTPException(status_code=404, detail="pedido não encontrado")
    return {"cliente": pedido.cliente, "status": pedido.status, "total": pedido.total}


def relatorio(limite: int = 10):
    return services.relatorio(limite)


async def quebra():
    dados = {"a": 1}
    return dados["b"]  # KeyError -> 500


def _register(app: FastAPI) -> None:
    app.middleware("http")(cabecalhos_seguranca)
    app.post("/pedidos")(criar_pedido)
    app.get("/pedidos/{pid}")(obter_pedido)
    app.get("/relatorio")(relatorio)
    app.get("/quebra")(quebra)

