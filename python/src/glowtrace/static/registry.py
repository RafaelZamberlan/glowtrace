"""Function registry: source parsing cache + lazy flow building.

Functions are identified by ``fn_id = "<rel_file>::<qualname>"``. Using the file
(not the module name) avoids duplicates when a project imports the same file
under two module names (e.g. ``api.routers.x`` and ``src.api.routers.x``).
"""
from __future__ import annotations

import ast
import inspect
import linecache
import os
import sys
import threading
import types
from dataclasses import dataclass
from typing import Any, Optional

from .flow import FunctionFlow, build_flow
from .resolver import FileFilter, FnContext, Resolver, unwrap_callable


@dataclass
class _FnEntry:
    qualname: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    class_path: list[str]  # enclosing classes (for self resolution)


class _FileIndex:
    def __init__(self, filename: str, source: str) -> None:
        self.filename = filename
        self.source = source
        self.lines = source.splitlines()
        self.tree = ast.parse(source, filename)
        self.by_line: dict[int, _FnEntry] = {}
        self.by_qualname: dict[str, _FnEntry] = {}
        self._index(self.tree, [], [])

    def _index(self, node: ast.AST, qual: list[str], classes: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qn = ".".join(qual + [child.name])
                entry = _FnEntry(qn, child, list(classes))
                self.by_qualname.setdefault(qn, entry)
                self.by_line[child.lineno] = entry
                if child.decorator_list:
                    self.by_line[child.decorator_list[0].lineno] = entry
                self._index(child, qual + [child.name, "<locals>"], [])
            elif isinstance(child, ast.ClassDef):
                self._index(child, qual + [child.name], classes + [child.name] if not qual or qual[-1] != "<locals>" else [])
            else:
                self._index(child, qual, classes)


class Registry:
    def __init__(self, roots: list[str], exclude: Optional[list[str]] = None) -> None:
        self.files = FileFilter(roots, exclude)
        self.resolver = Resolver(self.files, self.fn_id_for)
        self._files: dict[str, Optional[_FileIndex]] = {}
        self._flows: dict[str, FunctionFlow] = {}
        self._fn_loc: dict[str, tuple[str, str]] = {}  # fn_id -> (abs file, qualname)
        self._globals: dict[str, dict] = {}  # fn_id -> module globals
        self._code_ids: dict[Any, Optional[str]] = {}
        self._mod_by_file: dict[str, Any] = {}
        self._mod_count = -1
        self._lock = threading.RLock()

    # -- files ---------------------------------------------------------------
    def file_index(self, filename: str) -> Optional[_FileIndex]:
        idx = self._files.get(filename, _SENTINEL)
        if idx is not _SENTINEL:
            return idx  # type: ignore[return-value]
        with self._lock:
            if filename in self._files:
                return self._files[filename]
            try:
                lines = linecache.getlines(filename)
                source = "".join(lines)
                if not source:
                    with open(filename, encoding="utf-8") as fh:
                        source = fh.read()
                idx = _FileIndex(filename, source)
            except Exception:
                idx = None
            self._files[filename] = idx
            return idx

    # -- ids -------------------------------------------------------------------
    def fn_id_for(self, filename: str, firstlineno: int) -> Optional[str]:
        idx = self.file_index(filename)
        if idx is None:
            return None
        entry = idx.by_line.get(firstlineno)
        if entry is None:
            return None
        fid = f"{self.files.rel(filename)}::{entry.qualname}"
        self._fn_loc.setdefault(fid, (filename, entry.qualname))
        return fid

    def fn_id_for_code(self, code: types.CodeType) -> Optional[str]:
        try:
            return self._code_ids[code]
        except KeyError:
            pass
        fid = None
        if self.files(code.co_filename) and not code.co_name.startswith("<"):
            fid = self.fn_id_for(code.co_filename, code.co_firstlineno)
        self._code_ids[code] = fid
        return fid

    def register_callable(self, obj: Any) -> Optional[str]:
        fn = unwrap_callable(obj)
        if isinstance(fn, type):
            fn = fn.__dict__.get("__call__") or fn.__dict__.get("dispatch") or fn.__dict__.get("__init__")
            fn = unwrap_callable(fn) if fn is not None else None
        code = getattr(fn, "__code__", None)
        if code is None or not self.files(code.co_filename):
            return None
        fid = self.fn_id_for(code.co_filename, code.co_firstlineno)
        if fid is not None and getattr(fn, "__globals__", None) is not None:
            self._globals.setdefault(fid, fn.__globals__)
        return fid

    def remember_globals(self, fn_id: str, globals_: dict) -> None:
        self._globals.setdefault(fn_id, globals_)

    def describe_callable(self, obj: Any) -> str:
        fn = unwrap_callable(obj)
        mod = getattr(fn, "__module__", "") or ""
        name = getattr(fn, "__qualname__", None) or getattr(fn, "__name__", None) or type(fn).__name__
        return f"{mod}.{name}" if mod else str(name)

    # -- flows -----------------------------------------------------------------
    def flow(self, fn_id: str) -> Optional[FunctionFlow]:
        f = self._flows.get(fn_id)
        if f is not None:
            return f
        with self._lock:
            f = self._flows.get(fn_id)
            if f is not None:
                return f
            loc = self._fn_loc.get(fn_id)
            if loc is None:
                return None
            filename, qualname = loc
            idx = self.file_index(filename)
            if idx is None:
                return None
            entry = idx.by_qualname.get(qualname)
            if entry is None:
                return None
            globals_ = self._globals.get(fn_id) or self._module_globals(filename)
            cls = self._resolve_class(globals_, entry.class_path)
            ctx = FnContext(globals_, cls)
            ctx.local_types = self.resolver.local_types(entry.node, ctx)

            def classify(call: ast.Call, awaited: bool):
                return self.resolver.classify_call(call, ctx)

            f = build_flow(
                entry.node,
                fn_id=fn_id,
                qualname=qualname,
                file=filename,
                rel_file=self.files.rel(filename),
                source_lines=idx.lines,
                classify=classify,
            )
            self._flows[fn_id] = f
            return f

    def known_flows(self) -> list[str]:
        return list(self._flows)

    def reachable(self, roots: list[str], limit: int = 5000) -> list[str]:
        """BFS over resolved user calls starting at roots."""
        seen: list[str] = []
        queue = list(dict.fromkeys(r for r in roots if r))
        visited: set[str] = set()
        while queue and len(seen) < limit:
            fid = queue.pop(0)
            if fid in visited:
                continue
            visited.add(fid)
            f = self.flow(fid)
            if f is None:
                continue
            seen.append(fid)
            for n in f.nodes:
                for c in n.calls:
                    if c.kind == "user" and c.target and c.target not in visited:
                        queue.append(c.target)
        return seen

    # -- helpers -------------------------------------------------------------
    def _module_globals(self, filename: str) -> dict:
        target = os.path.normcase(os.path.abspath(filename))
        mod = self._mod_by_file.get(target)
        if mod is None and len(sys.modules) != self._mod_count:
            # (re)index only user modules; cheap and done once per module-count change
            self._mod_count = len(sys.modules)
            for m in list(sys.modules.values()):
                f = getattr(m, "__file__", None)
                if f and self.files(f):
                    self._mod_by_file.setdefault(os.path.normcase(os.path.abspath(f)), m)
            mod = self._mod_by_file.get(target)
        return vars(mod) if mod is not None else {}

    @staticmethod
    def _resolve_class(globals_: dict, class_path: list[str]) -> Optional[type]:
        if not class_path:
            return None
        obj: Any = globals_.get(class_path[0])
        for name in class_path[1:]:
            if obj is None:
                return None
            try:
                obj = inspect.getattr_static(obj, name)
            except AttributeError:
                return None
        return obj if isinstance(obj, type) else None


_SENTINEL = object()
