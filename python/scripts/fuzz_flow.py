"""Build flows for every function in a set of source trees and check invariants.

usage: python scripts/fuzz_flow.py <dir> [<dir> ...]

Invariants per function:
  * builder does not crash
  * nodes[0] is "start", nodes[-1] is "end", node ids == indexes
  * every edge points to existing nodes
  * every statement line of the function body (not nested defs) is owned by a node,
    so runtime line events can always be mapped
"""
from __future__ import annotations

import ast
import collections
import os
import sys
import time
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from easyapi.static.flow import build_flow  # noqa: E402

warnings.filterwarnings("ignore")


def stmt_lines(fn: ast.AST) -> list[int]:
    out: list[int] = []

    def walk(stmts):
        for i, s in enumerate(stmts):
            if isinstance(s, ast.Expr) and isinstance(getattr(s, "value", None), ast.Constant):
                continue  # docstrings / bare constants: compiled away, no line event
            out.append(s.lineno)
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for field in ("body", "orelse", "finalbody"):
                sub = getattr(s, field, None)
                if isinstance(sub, list) and sub and isinstance(sub[0], ast.stmt):
                    walk(sub)
            for h in getattr(s, "handlers", []) or []:
                out.append(h.lineno)
                walk(h.body)
            for c in getattr(s, "cases", []) or []:
                walk(c.body)

    walk(fn.body)
    return out


def main() -> None:
    files = funcs = 0
    problems: collections.Counter[str] = collections.Counter()
    examples: dict[str, str] = {}
    kinds: collections.Counter[str] = collections.Counter()
    t = time.time()
    for root in sys.argv[1:]:
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in ("__pycache__", ".venv", "node_modules", "site-packages", ".git")]
            for fn in fns:
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(dp, fn)
                try:
                    src = open(path, encoding="utf-8").read()
                    tree = ast.parse(src)
                except Exception:
                    continue
                files += 1
                lines = src.splitlines()
                for node in ast.walk(tree):
                    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    funcs += 1
                    where = f"{path}:{node.lineno}"
                    try:
                        fl = build_flow(node, fn_id="x", qualname=node.name, file=path, rel_file=fn, source_lines=lines)
                    except Exception as exc:
                        key = f"crash {type(exc).__name__}: {exc}"[:120]
                        problems[key] += 1
                        examples.setdefault(key, where)
                        continue
                    for n in fl.nodes:
                        kinds[n.kind] += 1
                    if fl.nodes[0].kind != "start" or fl.nodes[-1].kind != "end":
                        problems["start/end"] += 1
                        examples.setdefault("start/end", where)
                    if any(n.idx != i for i, n in enumerate(fl.nodes)):
                        problems["ids"] += 1
                    N = len(fl.nodes)
                    if any(not (0 <= e.source < N and 0 <= e.target < N) for e in fl.edges):
                        problems["edge out of range"] += 1
                        examples.setdefault("edge out of range", where)
                    missing = [ln for ln in stmt_lines(node) if ln not in fl.lines]
                    if missing:
                        problems["unmapped statement line"] += 1
                        examples.setdefault("unmapped statement line", f"{where} lines {missing[:5]}")
    dt = time.time() - t
    print(f"{files} files, {funcs} functions, {sum(kinds.values())} nodes in {dt:.1f}s ({funcs / dt:.0f} functions/s)")
    print("node kinds:", dict(kinds.most_common()))
    if not problems:
        print("OK: no invariant violations")
    for k, v in problems.most_common():
        print(f"  {v:>6}x {k}   e.g. {examples.get(k, '')}")


if __name__ == "__main__":
    main()
