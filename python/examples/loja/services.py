"""Domain services for the demo shop - deliberately full of branches and loops."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

ESTOQUE = {"camiseta": 10, "caneca": 0, "boné": 3}
PRECOS = {"camiseta": 59.9, "caneca": 29.9, "boné": 39.9}


class EstoqueInsuficiente(Exception):
    pass


@dataclass
class Pedido:
    cliente: str
    itens: list[dict]
    cupom: str | None = None
    total: float = 0.0
    status: str = "novo"
    avisos: list[str] = field(default_factory=list)


class RepositorioPedidos:
    def __init__(self) -> None:
        self._db: dict[int, Pedido] = {}

    def salvar(self, pedido: Pedido) -> int:
        pid = len(self._db) + 1
        self._db[pid] = pedido
        return pid

    def buscar(self, pid: int) -> Pedido | None:
        return self._db.get(pid)


repo = RepositorioPedidos()


def validar_itens(itens: list[dict]) -> list[str]:
    erros = []
    for item in itens:
        nome = item.get("produto")
        qtd = item.get("qtd", 1)
        if nome not in ESTOQUE:
            erros.append(f"produto inexistente: {nome}")
            continue
        if qtd <= 0:
            erros.append(f"quantidade inválida: {nome}")
        elif ESTOQUE[nome] < qtd:
            erros.append(f"sem estoque: {nome}")
    return erros


def aplicar_cupom(total: float, cupom: str | None) -> float:
    match cupom:
        case None:
            return total
        case "PRIMEIRA":
            desconto = 0.10
        case "VIP":
            desconto = 0.25
        case _:
            log.info("cupom desconhecido %s", cupom)
            return total
    return round(total * (1 - desconto), 2)


def calcular_total(pedido: Pedido) -> float:
    total = 0.0
    for item in pedido.itens:
        preco = PRECOS[item["produto"]]
        total += preco * item.get("qtd", 1)
    if total > 200:
        pedido.avisos.append("frete grátis")
    else:
        total += 15.0
    return aplicar_cupom(total, pedido.cupom)


async def cobrar(cliente: str, valor: float) -> dict:
    await asyncio.sleep(0.001)  # simula gateway de pagamento
    if valor > 1000:
        raise RuntimeError("limite do cartão excedido")
    return {"aprovado": True, "valor": valor, "cliente": cliente}


async def criar_pedido(pedido: Pedido) -> dict:
    erros = validar_itens(pedido.itens)
    if erros:
        raise EstoqueInsuficiente("; ".join(erros))
    pedido.total = calcular_total(pedido)
    try:
        pagamento = await cobrar(pedido.cliente, pedido.total)
    except RuntimeError as exc:
        pedido.status = "recusado"
        return {"status": pedido.status, "motivo": str(exc)}
    pedido.status = "pago" if pagamento["aprovado"] else "pendente"
    pid = repo.salvar(pedido)
    return {"id": pid, "status": pedido.status, "total": pedido.total, "avisos": pedido.avisos}


def relatorio(limite: int) -> dict:
    vistos = 0
    resumo = {}
    while vistos < limite:
        vistos += 1
        pedido = repo.buscar(vistos)
        if pedido is None:
            break
        resumo[pedido.status] = resumo.get(pedido.status, 0) + 1
    return {"analisados": vistos, "por_status": resumo}
