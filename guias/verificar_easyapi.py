"""Verifica se o EasyAPI está funcionando num app em execução (Python ou Java).

Uso (só biblioteca padrão, qualquer Python 3.8+):
    python verificar_easyapi.py http://127.0.0.1:8000            # app Python (prefixo /_easyapi)
    python verificar_easyapi.py http://127.0.0.1:7070            # agente Java (porta própria)
    python verificar_easyapi.py http://127.0.0.1:8000 --token XYZ
    python verificar_easyapi.py http://127.0.0.1:8000 --prefix /_easyapi --min-executions 1

Sai com código 0 se tudo estiver OK, 1 se algo falhar. Imprime um resumo pronto para relatório.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

OK, FAIL, WARN = "OK  ", "FALHA", "AVISO"


def main() -> int:
    try:  # Windows consoles/pipes default to cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("base", help="URL do app, ex.: http://127.0.0.1:8000")
    ap.add_argument("--prefix", default="/_easyapi")
    ap.add_argument("--token")
    ap.add_argument("--min-executions", type=int, default=0,
                    help="exige pelo menos N execuções gravadas (faça requisições antes)")
    a = ap.parse_args()
    base = a.base.rstrip("/") + a.prefix
    problems = 0

    def get(path: str):
        req = urllib.request.Request(base + path)
        if a.token:
            req.add_header("X-EasyAPI-Token", a.token)
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))

    def check(cond: bool, msg: str, level: str = FAIL) -> None:
        nonlocal problems
        if cond:
            print(f"[{OK}] {msg}")
        else:
            print(f"[{level}] {msg}")
            if level == FAIL:
                problems += 1

    # 1. meta
    try:
        meta = get("/api/meta")
    except urllib.error.HTTPError as e:
        print(f"[{FAIL}] {base}/api/meta respondeu HTTP {e.code}.")
        if e.code == 403:
            print("        403 = acesso fora do loopback. Use --token com o valor de EASYAPI_TOKEN.")
        if e.code == 404:
            print("        404 = EasyAPI não está instalado neste app (ou prefixo/porta errados).")
        return 1
    except Exception as e:  # conexão recusada etc.
        print(f"[{FAIL}] não consegui acessar {base}/api/meta: {e}")
        return 1
    print(f"[{OK}] EasyAPI ativo: app='{meta.get('title')}' modo={meta.get('mode')} "
          f"backend={meta.get('backend')} runtime={meta.get('runtime') or meta.get('python')}")
    check(meta.get("internal_errors", 0) == 0, f"erros internos do EasyAPI: {meta.get('internal_errors', 0)}")
    check(meta.get("mode") == "trace", "modo 'trace' (gravando execuções)", WARN)

    # 2. rotas
    data = get("/api/routes")
    routes = data.get("routes", [])
    with_handler = [r for r in routes if r.get("handler")]
    check(len(routes) > 0, f"rotas descobertas: {len(routes)}")
    check(len(with_handler) == len(routes),
          f"rotas com função mapeada: {len(with_handler)}/{len(routes)}"
          + ("" if len(with_handler) == len(routes) else " (as demais têm handler fora de EASYAPI_ROOTS)"), WARN)
    mws = data.get("middlewares", [])
    print(f"[{OK}] middlewares: {[m.get('name') for m in mws]}")

    # 3. um fluxo estático
    sample = with_handler[0] if with_handler else None
    if sample:
        try:
            fl = get("/api/function?id=" + urllib.parse.quote(sample["handler"]))
            kinds = {}
            for n in fl.get("nodes", []):
                kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1
            check(fl["nodes"][0]["kind"] == "start" and fl["nodes"][-1]["kind"] == "end",
                  f"fluxo de {sample['id']} -> {fl.get('qualname')} ({len(fl['nodes'])} nós: {kinds})")
        except Exception as e:
            check(False, f"fluxo do handler {sample['handler']}: {e}")
    else:
        check(False, "nenhuma rota com handler mapeado: confira EASYAPI_ROOTS (deve apontar para o código do app)")

    # 4. mapa
    try:
        m = get("/api/map")
        fns = m.get("functions", [])
        print(f"[{OK}] mapa da API: {len(fns)} funções, {len(m.get('edges', []))} chamadas, "
              f"{sum(f.get('branches', 0) for f in fns)} desvios")
    except Exception as e:
        check(False, f"mapa da API: {e}")

    # 5. execuções
    exs = get("/api/executions?limit=200").get("executions", [])
    check(len(exs) >= a.min_executions, f"execuções gravadas: {len(exs)} (mínimo exigido: {a.min_executions})")
    if not exs:
        print("        Faça algumas requisições ao app (curl/navegador/testes) e rode de novo com --min-executions 1.")
    for e in exs[:8]:
        err = f"  erro={e['error']['type']}: {str(e['error'].get('message'))[:60]}" if e.get("error") else ""
        print(f"        {e.get('status')} {e.get('method')} {e.get('path')} -> rota={e.get('route_id')} "
              f"funções={e.get('frame_count')} {e.get('duration_ms', 0):.1f}ms{err}")
    if exs:
        traced = [e for e in exs if e.get("frame_count")]
        check(len(traced) > 0, f"execuções com funções do app gravadas: {len(traced)}/{len(exs)}"
              + ("" if traced else " (nenhuma: confira EASYAPI_ROOTS)"))
        if traced:
            ex = get("/api/executions/" + urllib.parse.quote(traced[0]["id"]))
            frames = ex.get("frames", [])
            fns = {f["fn"] for f in frames}
            missing = []
            for fn in fns:
                try:
                    get("/api/function?id=" + urllib.parse.quote(fn))
                except Exception:
                    missing.append(fn)
            check(not missing, f"execução {ex['id']}: {len(frames)} frames, fluxo disponível para todas as funções"
                  + (f" (faltando: {missing[:3]})" if missing else ""))
            with_path = sum(1 for f in frames if f.get("path"))
            check(with_path > 0, f"frames com caminho percorrido (linhas/branches): {with_path}/{len(frames)}")
            print(f"        abra: {a.base.rstrip('/')}{a.prefix}/#route={urllib.parse.quote(str(ex.get('route_id')))}&exec={ex['id']}")

    print()
    print("RESULTADO:", "OK" if problems == 0 else f"{problems} problema(s)")
    print(f"UI: {a.base.rstrip('/')}{a.prefix}/")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
