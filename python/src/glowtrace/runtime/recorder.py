"""Per-request execution recorder.

A ``Recorder`` lives in a ContextVar for the duration of one request. Anything
that runs in that context - the endpoint, awaited coroutines, tasks created from
it, and sync endpoints/dependencies run by anyio in a worker thread (anyio copies
the context) - reports into it. Code running for other requests sees a
different (or no) recorder, so concurrent requests never mix.
"""
from __future__ import annotations

import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Optional

from ..static.registry import Registry
from .capture import Capturer

current: ContextVar[Optional["Recorder"]] = ContextVar("glowtrace_recorder", default=None)


@dataclass
class Limits:
    max_frames: int = 3000
    max_path: int = 4000  # node visits kept per frame
    max_values: int = 300  # value snapshots per frame
    max_values_per_node: int = 5  # loops: values of the first N passes per node


class FrameRec:
    __slots__ = (
        "id",
        "parent",
        "fn_id",
        "call_line",
        "args",
        "ret",
        "exc",
        "raised",
        "start",
        "end",
        "path",
        "values",
        "lines",
        "nodes",
        "last",
        "pending",
        "truncated",
        "overflow",
        "exc_pending",
        "thread",
        "vcount",
    )

    def __init__(self, id_: int, fn_id: str, flow, parent: Optional["FrameRec"], call_line: Optional[int], start: int):
        self.id = id_
        self.parent = parent.id if parent is not None else None
        self.fn_id = fn_id
        self.call_line = call_line
        self.args: dict = {}
        self.ret: Any = None
        self.exc: Optional[dict] = None
        self.raised: list = []
        self.start = start
        self.end: Optional[int] = None
        self.path: list[list[int]] = []  # [node_idx, t_us]
        self.values: list[list] = []  # [path_pos, {name: value}, "before"|"after"]
        self.lines = flow.lines
        self.nodes = flow.nodes
        self.last: Optional[int] = None
        self.pending: Optional[tuple[int, list[str]]] = None
        self.truncated = False
        self.overflow: dict[int, int] = {}
        self.exc_pending: Any = None
        self.thread = None
        self.vcount: dict[int, int] = {}

    def to_json(self, source_hash: Optional[str]) -> dict:
        d = {
            "id": self.id,
            "parent": self.parent,
            "fn": self.fn_id,
            "call_line": self.call_line,
            "args": self.args,
            "start_us": self.start,
            "end_us": self.end,
            "path": self.path,
            "values": self.values,
            "hash": source_hash,
        }
        if self.exc is not None:
            d["exception"] = self.exc
        else:
            d["return"] = self.ret
        if self.raised:
            d["raised"] = self.raised
        if self.truncated:
            d["truncated"] = True
            d["overflow"] = {str(k): v for k, v in self.overflow.items()}
        if self.end is None:
            d["incomplete"] = True
        return d


class Recorder:
    def __init__(self, registry: Registry, capturer: Capturer, limits: Optional[Limits] = None) -> None:
        self.id = uuid.uuid4().hex[:16]
        self.registry = registry
        self.cap = capturer
        self.limits = limits or Limits()
        self.frames: list[FrameRec] = []
        self.live: dict[int, FrameRec] = {}
        self.t0 = time.perf_counter_ns()
        self.started_at = time.time()
        self.closed = False
        self.truncated = False
        self.replay_of: Optional[str] = None  # id of the recorded execution this request replays
        self.replay_edits: list[str] = []

    def _now(self) -> int:
        return (time.perf_counter_ns() - self.t0) // 1000

    # -- events ------------------------------------------------------------------
    def on_start(self, frame, code) -> None:
        if self.closed:
            return
        fid = self.registry.fn_id_for_code(code)
        if fid is None:
            return
        if len(self.frames) >= self.limits.max_frames:
            self.truncated = True
            return
        self.registry.remember_globals(fid, frame.f_globals)
        flow = self.registry.flow(fid)
        if flow is None:
            return
        parent = None
        call_line = None
        f = frame.f_back
        steps = 0
        live = self.live
        while f is not None and steps < 64:
            p = live.get(id(f))
            if p is not None:
                parent = p
                call_line = f.f_lineno
                break
            f = f.f_back
            steps += 1
        rec = FrameRec(len(self.frames), fid, flow, parent, call_line, self._now())
        try:
            loc = frame.f_locals
            args = {}
            for p in flow.params:
                name = p.lstrip("*")
                if name not in loc:
                    continue
                if name in ("self", "cls"):
                    obj = loc[name]
                    args[name] = f"<{obj.__name__ if isinstance(obj, type) else type(obj).__name__}>"
                else:
                    args.update(self.cap.capture_mapping(loc, [name]))
            rec.args = args
        except Exception:
            rec.args = {}
        live[id(frame)] = rec
        self.frames.append(rec)

    def on_line(self, frame, line: int) -> None:
        rec = self.live.get(id(frame))
        if rec is None:
            return
        rec.exc_pending = None  # a line ran after an exception -> it was handled
        node = rec.lines.get(line)
        if node is None or node == rec.last:
            return
        rec.last = node
        if rec.pending is not None:
            self._flush_pending(rec, frame)
        if len(rec.path) >= self.limits.max_path:
            rec.truncated = True
            rec.overflow[node] = rec.overflow.get(node, 0) + 1
            return
        pos = len(rec.path)
        rec.path.append([node, self._now()])
        n = rec.nodes[node]
        if not (n.watch or n.assigns):
            return
        seen = rec.vcount.get(node, 0)
        if seen >= self.limits.max_values_per_node:
            return
        rec.vcount[node] = seen + 1
        if n.watch and len(rec.values) < self.limits.max_values:
            try:
                vals = self.cap.capture_mapping(frame.f_locals, n.watch)
            except Exception:
                vals = {}
            if vals:
                rec.values.append([pos, vals, "before"])
        if n.assigns:
            rec.pending = (pos, n.assigns)

    def _flush_pending(self, rec: FrameRec, frame) -> None:
        pos, names = rec.pending  # type: ignore[misc]
        rec.pending = None
        if len(rec.values) >= self.limits.max_values:
            return
        try:
            loc = frame.f_locals
            plain = [n for n in names if "." not in n]
            vals = self.cap.capture_mapping(loc, plain)
            for dotted in (n for n in names if "." in n):
                base, *rest = dotted.split(".")
                if base in loc and len(rest) == 1:
                    try:
                        d = object.__getattribute__(loc[base], "__dict__")
                        if rest[0] in d:
                            vals[dotted] = self.cap.capture_mapping(d, [rest[0]]).get(rest[0])
                    except Exception:
                        pass
        except Exception:
            vals = {}
        if vals:
            rec.values.append([pos, vals, "after"])

    def on_return(self, frame, value: Any) -> None:
        rec = self.live.pop(id(frame), None)
        if rec is None:
            return
        if rec.pending is not None:
            self._flush_pending(rec, frame)
        rec.ret = self.cap.capture(value)
        rec.end = self._now()

    def on_unwind(self, frame, exc: BaseException) -> None:
        rec = self.live.pop(id(frame), None)
        if rec is None:
            return
        rec.exc = {
            "type": type(exc).__name__,
            "message": self.cap.scrub_text(_exc_message(exc)),
            "line": frame.f_lineno,
        }
        detail = getattr(exc, "detail", None)
        status = getattr(exc, "status_code", None)
        if detail is not None:
            rec.exc["detail"] = self.cap.capture(detail)
        if isinstance(status, int):
            rec.exc["status_code"] = status
        rec.end = self._now()

    def on_raise(self, frame, exc: BaseException) -> None:
        rec = self.live.get(id(frame))
        if rec is None or len(rec.raised) >= 20:
            return
        rec.raised.append({"line": frame.f_lineno, "type": type(exc).__name__, "message": self.cap.scrub_text(_exc_message(exc))[:200]})

    # -- result ------------------------------------------------------------------
    def close(self) -> None:
        self.closed = True

    def frames_json(self) -> list[dict]:
        out = []
        for f in self.frames:
            flow = self.registry.flow(f.fn_id)
            out.append(f.to_json(flow.source_hash if flow else None))
        return out


def _exc_message(exc: BaseException) -> str:
    try:
        detail = getattr(exc, "detail", None)
        if detail is not None and not str(exc):
            return str(detail)
        return str(exc)
    except Exception:
        return type(exc).__name__
