"""Overhead benchmark: in-process ASGI requests against the demo shop.

usage: python benchmarks/bench_overhead.py <mode> [n]
  mode: baseline | off | graph | trace | trace-sampled0
Prints: mode, python, backend, mean/p50/p95 latency (ms), requests/s.
"""
import asyncio
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import httpx  # noqa: E402

from examples.loja.main import create_app  # noqa: E402

AUTH = {"Authorization": "Bearer bench.sig"}
BODY = {"cliente": "bench", "itens": [{"produto": "camiseta", "qtd": 2}, {"produto": "boné", "qtd": 1}], "cupom": "VIP"}


def cpu_app():
    """Worst case: pure-CPU endpoint, ~50-iteration loops with branches, no I/O."""
    from fastapi import FastAPI

    from examples.loja import services

    app = FastAPI()

    @app.post("/pedidos")
    async def calc(body: dict):
        itens = [{"produto": p, "qtd": q} for p, q in zip(["camiseta", "boné", "caneca", "xyz"] * 13, range(52))]
        pedido = services.Pedido(cliente=body["cliente"], itens=[i for i in itens if i["produto"] != "xyz"], cupom="VIP")
        erros = services.validar_itens(itens)
        total = services.calcular_total(pedido)
        return {"total": total, "erros": len(erros)}

    return app


def main() -> None:
    mode = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 400
    app = cpu_app() if os.environ.get("BENCH_CPU") else create_app()
    backend = None
    if mode != "baseline":
        from glowtrace import Glowtrace

        kw = {"store": "memory", "roots": [os.path.dirname(HERE)]}
        if os.environ.get("BENCH_NO_VALUES"):
            from glowtrace import Limits

            kw["limits"] = Limits(max_values=0)
        if mode == "trace-sampled0":
            kw.update(mode="trace", sample_rate=0.0)
        else:
            kw.update(mode=mode)
        ez = Glowtrace(app, **kw)
        backend = ez.backend.name if ez.backend else None

    async def run() -> list[float]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://bench") as c:
            for _ in range(30):  # warm-up
                await c.post("/pedidos", json=BODY, headers=AUTH)
            lat = []
            for _ in range(n):
                t = time.perf_counter()
                r = await c.post("/pedidos", json=BODY, headers=AUTH)
                lat.append((time.perf_counter() - t) * 1000)
                assert r.status_code == 200, r.text
            return lat

    t0 = time.perf_counter()
    lat = asyncio.run(run())
    total = time.perf_counter() - t0
    lat.sort()
    print(
        f"{mode:<15} py{sys.version_info[0]}.{sys.version_info[1]:<3} backend={str(backend):<15} "
        f"mean={statistics.mean(lat):6.3f}ms p50={lat[len(lat)//2]:6.3f}ms p95={lat[int(len(lat)*0.95)]:6.3f}ms "
        f"rps={n/total:7.1f}"
    )


if __name__ == "__main__":
    main()
