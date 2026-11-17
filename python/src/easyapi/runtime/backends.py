"""Tracing backends.

* ``MonitoringBackend`` (Python 3.12+, PEP 669 ``sys.monitoring``): code that is
  not user code gets ``DISABLE`` on its first event, after which the interpreter
  stops reporting it - library/stdlib code runs at (almost) full speed.
* ``SettraceBackend`` (Python 3.10/3.11): classic ``sys.settrace``; the global
  trace function returns ``None`` immediately unless a recorder is active *and*
  the frame is user code, so only traced requests pay for line events.
"""
from __future__ import annotations

import dis
import sys
import threading
from typing import Optional

from ..static.registry import Registry
from .recorder import current


class Backend:
    """One tracer per process, shared by every EasyAPI instance (see acquire_backend)."""

    name = "none"

    def __init__(self, registry: Registry) -> None:
        self.registries: list[Registry] = [registry]
        self._user: dict = {}

    @property
    def registry(self) -> Registry:
        return self.registries[0]

    def add_registry(self, registry: Registry) -> None:
        if any(r.files.roots == registry.files.roots and r.files.exclude == registry.files.exclude for r in self.registries):
            self.registries.append(registry)
            return
        self.registries.append(registry)
        self._user.clear()  # new roots: "user code" changed
        self.reset_disabled()

    def remove_registry(self, registry: Registry) -> None:
        self.registries = [r for r in self.registries if r is not registry]

    def reset_disabled(self) -> None:
        """Forget per-location DISABLE decisions (sys.monitoring only)."""

    def is_user(self, code) -> bool:
        try:
            return self._user[code]
        except KeyError:
            ok = any(r.fn_id_for_code(code) is not None for r in self.registries)
            self._user[code] = ok
            return ok

    def install(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def begin(self) -> None:
        """A traced request starts on the current thread."""

    def end(self) -> None:
        """A traced request finished on the current thread."""

    def uninstall(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class MonitoringBackend(Backend):
    name = "sys.monitoring"

    def __init__(self, registry: Registry) -> None:
        super().__init__(registry)
        self.tool: Optional[int] = None
        self._lock = threading.Lock()
        self._active = 0
        self._events = 0

    def install(self) -> None:
        mon = sys.monitoring
        for tool in (4, 3, 2, 5):
            if mon.get_tool(tool) is None:
                mon.use_tool_id(tool, "easyapi")
                self.tool = tool
                break
        else:
            raise RuntimeError("easyapi: no free sys.monitoring tool id")
        mon.restart_events()  # forget DISABLEs left by a previous install
        E = mon.events
        DISABLE = mon.DISABLE
        is_user = self.is_user
        getframe = sys._getframe

        def on_start(code, offset):
            if not is_user(code):
                return DISABLE
            rec = current.get()
            if rec is not None:
                rec.on_start(getframe(1), code)

        def on_line(code, line):
            if not is_user(code):
                return DISABLE
            rec = current.get()
            if rec is not None:
                rec.on_line(getframe(1), line)

        def on_return(code, offset, retval):
            if not is_user(code):
                return DISABLE
            rec = current.get()
            if rec is not None:
                rec.on_return(getframe(1), retval)

        def on_unwind(code, offset, exc):  # cannot be disabled
            rec = current.get()
            if rec is not None and is_user(code):
                rec.on_unwind(getframe(1), exc)

        def on_raise(code, offset, exc):  # cannot be disabled
            rec = current.get()
            if rec is not None and is_user(code):
                rec.on_raise(getframe(1), exc)

        t = self.tool
        mon.register_callback(t, E.PY_START, on_start)
        mon.register_callback(t, E.LINE, on_line)
        mon.register_callback(t, E.PY_RETURN, on_return)
        mon.register_callback(t, E.PY_UNWIND, on_unwind)
        mon.register_callback(t, E.RAISE, on_raise)
        self._events = E.PY_START | E.LINE | E.PY_RETURN | E.PY_UNWIND | E.RAISE
        # Events stay OFF until a traced request starts (begin/end below), so
        # untraced requests run with zero monitoring cost. DISABLEd (library)
        # locations stay disabled across on/off cycles.

    def begin(self) -> None:
        with self._lock:
            self._active += 1
            if self._active == 1 and self.tool is not None:
                sys.monitoring.set_events(self.tool, self._events)

    def end(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)
            if self._active == 0 and self.tool is not None:
                sys.monitoring.set_events(self.tool, 0)

    def reset_disabled(self) -> None:
        if self.tool is not None:
            sys.monitoring.restart_events()

    def uninstall(self) -> None:
        if self.tool is None:
            return
        mon = sys.monitoring
        mon.set_events(self.tool, 0)
        for ev in (mon.events.PY_START, mon.events.LINE, mon.events.PY_RETURN, mon.events.PY_UNWIND, mon.events.RAISE):
            mon.register_callback(self.tool, ev, None)
        mon.free_tool_id(self.tool)
        self.tool = None


# A 'return' trace event is a real return only if the frame stopped on a RETURN
# opcode; otherwise the coroutine/generator was suspended (await/yield). Checking
# for the return op is robust across versions (3.10 parks f_lasti on the
# LOAD_CONST *before* YIELD_FROM while awaiting).
_RETURN_OPS = {dis.opmap[n] for n in ("RETURN_VALUE", "RETURN_CONST", "RETURN_GENERATOR") if n in dis.opmap}
_GENERATOR_FLAGS = 0x20 | 0x80 | 0x100 | 0x200  # GENERATOR | COROUTINE | ITERABLE_COROUTINE | ASYNC_GENERATOR
_CONTROL_FLOW_EXC = (StopIteration, StopAsyncIteration, GeneratorExit)


class SettraceBackend(Backend):
    name = "sys.settrace"

    def __init__(self, registry: Registry) -> None:
        super().__init__(registry)
        self._prev = None
        self._lock = threading.Lock()
        self._active: dict[int, int] = {}

    def install(self) -> None:
        is_user = self.is_user

        def local(frame, event, arg):
            rec = current.get()
            if rec is None:
                return None
            if event == "line":
                rec.on_line(frame, frame.f_lineno)
            elif event == "return":
                fr = rec.live.get(id(frame))
                if fr is not None and fr.exc_pending is not None:
                    rec.on_unwind(frame, fr.exc_pending)
                    return local
                code = frame.f_code
                if code.co_flags & _GENERATOR_FLAGS:
                    try:
                        if code.co_code[frame.f_lasti] not in _RETURN_OPS:
                            return local  # suspended at await/yield, not finished
                    except Exception:
                        pass
                rec.on_return(frame, arg)
            elif event == "exception":
                etype = arg[0] if isinstance(arg, tuple) and arg else type(arg)
                if etype in _CONTROL_FLOW_EXC:
                    # `await`/`yield from` deliver results via StopIteration: not an error
                    return local
                exc = arg[1] if isinstance(arg, tuple) and len(arg) > 1 else arg
                fr = rec.live.get(id(frame))
                if fr is not None:
                    if fr.exc_pending is None:
                        rec.on_raise(frame, exc)
                    fr.exc_pending = exc
            return local

        def global_trace(frame, event, arg):
            if event != "call":
                return None
            rec = current.get()
            if rec is None:
                return None
            code = frame.f_code
            if not is_user(code):
                return None
            if id(frame) not in rec.live:
                rec.on_start(frame, code)
                if id(frame) not in rec.live:
                    return None
            return local

        self._global = global_trace
        self._prev = sys.gettrace()
        # Worker threads (anyio's threadpool runs sync endpoints/dependencies) are
        # created lazily, so they inherit the tracer. The event-loop thread is
        # toggled on demand in begin()/end(): while no traced request is in
        # flight it runs with no tracer at all (zero overhead).
        threading.settrace(global_trace)

    def begin(self) -> None:
        """Called on the event-loop thread when a traced request starts."""
        with self._lock:
            self._active[threading.get_ident()] = self._active.get(threading.get_ident(), 0) + 1
            if sys.gettrace() is not self._global:
                sys.settrace(self._global)

    def end(self) -> None:
        tid = threading.get_ident()
        with self._lock:
            n = self._active.get(tid, 1) - 1
            if n <= 0:
                self._active.pop(tid, None)
                if sys.gettrace() is self._global:
                    sys.settrace(self._prev)
            else:
                self._active[tid] = n

    def uninstall(self) -> None:
        threading.settrace(None)  # type: ignore[arg-type]
        if sys.gettrace() is self._global:
            sys.settrace(self._prev)


def make_backend(registry: Registry, prefer: Optional[str] = None) -> Backend:
    if prefer == "settrace" or not hasattr(sys, "monitoring"):
        return SettraceBackend(registry)
    return MonitoringBackend(registry)


_shared: Optional[Backend] = None
_shared_lock = threading.Lock()


def acquire_backend(registry: Registry, prefer: Optional[str] = None) -> Backend:
    """Process-wide tracer: installed by the first EasyAPI instance, shared by the
    others (apps mounted in apps, test suites that build many apps...)."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = make_backend(registry, prefer)
            _shared.install()
        else:
            _shared.add_registry(registry)
        return _shared


def release_backend(registry: Registry) -> None:
    global _shared
    with _shared_lock:
        if _shared is None:
            return
        _shared.remove_registry(registry)
        if not _shared.registries:
            _shared.uninstall()
            _shared = None
