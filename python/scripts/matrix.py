"""Compatibility matrix: run the test suite across Python x FastAPI versions.

Each cell runs in an isolated, ephemeral `uv run` environment.

usage: python scripts/matrix.py [--py 3.11,3.13] [--fa 0.100.1,0.162.5] [--jobs 6] [--out FILE.md]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
LOGS = os.path.join(os.path.dirname(PKG), ".sandbox", "matrix")

PYTHONS = ["3.10", "3.11", "3.12", "3.13", "3.14", "3.14t", "3.15"]
FASTAPIS = [
    "0.95.2",  # pydantic v1, starlette 0.27 (eager middleware stack)
    "0.100.1",  # first pydantic v2
    "0.104.1",
    "0.110.3",
    "0.115.14",
    "0.120.4",
    "0.128.8",
    "0.135.4",
    "0.145.0",
    "0.150.0",
    "0.156.8",
    "0.162.5",  # lazy _IncludedRouter
]


def vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def run_cell(py: str, fa: str) -> tuple[str, str, str, float, str]:
    httpx = "httpx<0.28" if vtuple(fa) < (0, 120, 0) else "httpx"
    cmd = [
        "uv", "run", "--no-project", "--isolated", "--quiet",
        "--python", py,
        "--with", f"fastapi=={fa}",
        "--with", httpx,
        "--with", "pytest",
        "--with-editable", PKG,
        "--", "python", "-m", "pytest", "-q", "-p", "no:cacheprovider",
        "-W", "ignore::DeprecationWarning", os.path.join(PKG, "tests"),
    ]
    t = time.time()
    proc = subprocess.run(cmd, cwd=PKG, capture_output=True, text=True, encoding="utf-8", errors="replace")
    dt = time.time() - t
    out = proc.stdout + proc.stderr
    os.makedirs(LOGS, exist_ok=True)
    with open(os.path.join(LOGS, f"py{py}-fa{fa}.log"), "w", encoding="utf-8") as fh:
        fh.write(" ".join(cmd) + "\n\n" + out)
    m = re.search(r"(\d+) passed", out)
    f = re.search(r"(\d+) failed", out)
    e = re.search(r"(\d+) error", out)
    passed = int(m.group(1)) if m else 0
    if proc.returncode == 0 and passed:
        return py, fa, "ok", dt, f"{passed}"
    if passed or f or e:
        return py, fa, "fail", dt, f"{passed} ok / {f.group(1) if f else 0} falhas / {e.group(1) if e else 0} erros"
    last = [ln for ln in out.strip().splitlines() if ln.strip()][-1:] or ["?"]
    return py, fa, "env", dt, last[0][:160]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--py", default=",".join(PYTHONS))
    ap.add_argument("--fa", default=",".join(FASTAPIS))
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--out")
    a = ap.parse_args()
    pys, fas = a.py.split(","), a.fa.split(",")
    results: dict[tuple[str, str], tuple] = {}
    with cf.ThreadPoolExecutor(a.jobs) as ex:
        futs = [ex.submit(run_cell, p, f) for p in pys for f in fas]
        for fut in cf.as_completed(futs):
            py, fa, status, dt, info = fut.result()
            results[(py, fa)] = (status, dt, info)
            print(f"py{py:<6} fastapi {fa:<9} {status:<5} {dt:5.0f}s  {info}", flush=True)
    icon = {"ok": "✅", "fail": "❌", "env": "⚠️"}
    lines = ["| Python \\ FastAPI | " + " | ".join(fas) + " |", "|---|" + "---|" * len(fas)]
    for p in pys:
        lines.append(f"| {p} | " + " | ".join(icon[results[(p, f)][0]] for f in fas) + " |")
    notes = [f"- py{p} × fastapi {f}: {results[(p, f)][2]}" for p in pys for f in fas if results[(p, f)][0] != "ok"]
    table = "\n".join(lines) + ("\n\nNotas:\n" + "\n".join(notes) if notes else "")
    print("\n" + table)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(table + "\n")


if __name__ == "__main__":
    main()
