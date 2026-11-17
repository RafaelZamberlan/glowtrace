"""`python -m easyapi run <command...>` - run any Python command with EasyAPI auto-instrumentation.

Example:
    python -m easyapi run uvicorn main:app --port 8000

It works like `opentelemetry-instrument`: a `sitecustomize` module placed first on
PYTHONPATH calls `easyapi.auto.install()` in the child process, so no code change is
needed. Configure with EASYAPI_* environment variables.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

BOOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_bootstrap")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help") or argv[0] != "run" or len(argv) < 2:
        print(__doc__)
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    cmd = argv[1:]
    env = dict(os.environ)
    env["PYTHONPATH"] = BOOT + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["EASYAPI_AUTO"] = "1"
    return subprocess.call(_resolve(cmd), env=env)


def _resolve(cmd: list[str]) -> list[str]:
    """Prefer the current interpreter / environment over whatever is first on PATH."""
    head = os.path.basename(cmd[0]).lower()
    if cmd[0] == "-m" or head in ("python", "python3", "python.exe", "python3.exe"):
        return [sys.executable] + (cmd if cmd[0] == "-m" else cmd[1:])
    here = os.path.dirname(sys.executable)  # venv Scripts/ or bin/: console scripts live here
    exe = shutil.which(cmd[0], path=here) or shutil.which(cmd[0]) or cmd[0]
    return [exe] + cmd[1:]


if __name__ == "__main__":
    raise SystemExit(main())
