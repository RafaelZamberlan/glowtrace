"""pytest plugin: `pytest -p glowtrace.pytest_plugin` instruments every app the suite builds.

At the end it prints how many apps/executions were recorded and any internal errors.
"""
from __future__ import annotations

from . import auto


def pytest_configure(config):  # noqa: D401
    auto.install()


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    apps = auto.instances
    if not apps:
        terminalreporter.write_line("glowtrace: no ASGI app was instrumented")
        return
    errors = sum(a.internal_errors for a in apps)
    stores = {id(a.store): a.store for a in apps}
    total = 0
    for st in stores.values():
        try:
            st.flush(5)
            total += len(st.list(limit=1_000_000))
        except Exception:
            pass
    terminalreporter.write_line(
        f"glowtrace: {len(apps)} apps instrumented, {total} executions stored, {errors} internal errors"
    )
    import os

    if os.environ.get("GLOWTRACE_SELFCHECK") == "1":
        _selfcheck(terminalreporter, apps)


def _selfcheck(tr, apps) -> None:
    """Overlay every stored execution; report frames whose path the static graph
    cannot explain ("jumps") - a quality metric for the line->node mapping."""
    import collections

    from .overlay import overlay_execution

    frames = jumps_total = overlay_errors = missing = 0
    jump_examples: "collections.Counter[str]" = collections.Counter()
    for app in apps:
        for summ in app.store.list(limit=1_000_000):
            ex = app.store.get(summ["id"])
            if not ex:
                continue
            try:
                ov = overlay_execution(ex, app.registry)
            except Exception as exc:  # pragma: no cover - reported
                overlay_errors += 1
                jump_examples[f"overlay error {type(exc).__name__}: {exc}"] += 1
                continue
            for fr, o in zip(ex["frames"], ov["frames"]):
                frames += 1
                if o.get("missing"):
                    missing += 1
                for a, b in o.get("jumps", []):
                    jumps_total += 1
                    flow = app.registry.flow(fr["fn"])
                    if flow is not None:
                        na, nb = flow.nodes[a], flow.nodes[b]
                        jump_examples[f"{flow.rel_file}:{na.line} {na.kind} -> {nb.kind} (line {nb.line})"] += 1
    tr.write_line(
        f"glowtrace selfcheck: {frames} frames, {jumps_total} unexplained transitions, "
        f"{missing} frames without flow, {overlay_errors} overlay errors"
    )
    for k, v in jump_examples.most_common(15):
        tr.write_line(f"   {v:>4}x {k}")
