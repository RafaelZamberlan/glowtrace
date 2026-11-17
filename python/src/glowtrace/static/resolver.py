"""Resolve call expressions to concrete functions using the *live* application.

Glowtrace runs inside the target process, so instead of guessing a call graph from
source alone we evaluate the callee expression against the real module globals
(``func.__globals__``) using ``inspect.getattr_static`` - which never triggers
properties/descriptors, so resolution has no side effects.

Resolution kinds:
    user        -> a Python function defined in the project (expandable)
    external    -> third-party library (an "integration" node: httpx, pymongo...)
    stdlib      -> standard library (trivial unless it is I/O)
    builtin     -> len/str/print...
    unresolved  -> dynamic dispatch; runtime observations fill these in
"""
from __future__ import annotations

import ast
import builtins
import functools
import inspect
import os
import sys
import sysconfig
import types
from typing import Any, Callable, Optional

from .flow import CallInfo

_MISSING = object()

_STDLIB_IO = {
    "subprocess",
    "socket",
    "smtplib",
    "urllib",
    "http",
    "ftplib",
    "sqlite3",
    "shutil",
    "asyncio",
}


def _stdlib_dirs() -> list[str]:
    dirs = set()
    for key in ("stdlib", "platstdlib"):
        p = sysconfig.get_paths().get(key)
        if p:
            dirs.add(os.path.normcase(os.path.abspath(p)))
    return sorted(dirs)


_STDLIB = _stdlib_dirs()
_STDLIB_NAMES = getattr(sys, "stdlib_module_names", frozenset())


class FileFilter:
    """Decides whether a source file is *user code*."""

    _BLOCK = (
        "site-packages",
        "dist-packages",
        f"{os.sep}.venv{os.sep}",
        f"{os.sep}venv{os.sep}",
        f"{os.sep}.tox{os.sep}",
        f"{os.sep}node_modules{os.sep}",
    )

    def __init__(self, roots: list[str], exclude: Optional[list[str]] = None) -> None:
        self.roots = [os.path.normcase(os.path.abspath(r)) for r in roots]
        self.exclude = [os.path.normcase(os.path.abspath(e)) for e in (exclude or [])]
        self._own = os.path.normcase(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self._cache: dict[str, bool] = {}

    def __call__(self, filename: str) -> bool:
        hit = self._cache.get(filename)
        if hit is not None:
            return hit
        ok = self._check(filename)
        self._cache[filename] = ok
        return ok

    def _check(self, filename: str) -> bool:
        if not filename or filename.startswith("<"):
            return False
        path = os.path.normcase(os.path.abspath(filename))
        if path.startswith(self._own):
            return False
        if any(b in path for b in self._BLOCK):
            return False
        if any(path.startswith(s + os.sep) for s in _STDLIB):
            return False
        if any(path.startswith(e) for e in self.exclude):
            return False
        return any(path.startswith(r + os.sep) or path == r for r in self.roots)

    def rel(self, filename: str) -> str:
        path = os.path.abspath(filename)
        npath = os.path.normcase(path)
        for r in self.roots:
            if npath.startswith(r + os.sep):
                return path[len(r) + 1 :].replace(os.sep, "/")
        return path.replace(os.sep, "/")


def unwrap_callable(obj: Any) -> Any:
    """Peel decorators / descriptors until we reach a plain function if possible."""
    for _ in range(10):
        if isinstance(obj, (staticmethod, classmethod)):
            obj = obj.__func__
            continue
        if isinstance(obj, property):
            obj = obj.fget
            continue
        if isinstance(obj, functools.partial):
            obj = obj.func
            continue
        if isinstance(obj, types.MethodType):
            obj = obj.__func__
            continue
        wrapped = getattr(obj, "__wrapped__", None) if not isinstance(obj, type) else None
        if wrapped is not None and wrapped is not obj:
            obj = wrapped
            continue
        break
    return obj


def module_lib(obj: Any) -> Optional[str]:
    mod = getattr(obj, "__module__", None)
    if not isinstance(mod, str):
        if isinstance(obj, types.ModuleType):
            mod = obj.__name__
        else:
            mod = getattr(type(obj), "__module__", None)
    if not isinstance(mod, str):
        return None
    return mod.split(".")[0]


class FnContext:
    """Name-resolution context for one function."""

    def __init__(
        self,
        globals_: dict,
        cls: Optional[type] = None,
        local_types: Optional[dict[str, Any]] = None,
    ) -> None:
        self.globals = globals_ or {}
        self.cls = cls
        self.local_types = local_types or {}


class Resolver:
    def __init__(self, files: FileFilter, fn_id_for: Callable[[str, int], Optional[str]]) -> None:
        self.files = files
        self.fn_id_for = fn_id_for

    # -- expression evaluation (static, side-effect free) ------------------
    def _eval(self, expr: ast.AST, ctx: FnContext, depth: int = 0) -> Any:
        if depth > 8:
            return _MISSING
        if isinstance(expr, ast.Name):
            if expr.id in ("self", "cls") and ctx.cls is not None:
                return ctx.cls
            if expr.id in ctx.local_types:
                return ctx.local_types[expr.id]
            if expr.id in ctx.globals:
                return ctx.globals[expr.id]
            return getattr(builtins, expr.id, _MISSING)
        if isinstance(expr, ast.Attribute):
            base = self._eval(expr.value, ctx, depth + 1)
            if base is _MISSING:
                return _MISSING
            if isinstance(base, _Instance):
                try:
                    return inspect.getattr_static(base.cls, expr.attr)
                except AttributeError:
                    return _MISSING
            try:
                return inspect.getattr_static(base, expr.attr)
            except AttributeError:
                # instance attribute set in __init__ etc.: look on the class
                try:
                    return inspect.getattr_static(type(base), expr.attr)
                except AttributeError:
                    return _MISSING
        if isinstance(expr, ast.Call):
            # X(...).method -> if X is a class, the result is an instance of X
            callee = self._eval(expr.func, ctx, depth + 1)
            if isinstance(callee, type):
                return _Instance(callee)
            return _MISSING
        return _MISSING

    def classify_obj(self, obj: Any, expr: str) -> CallInfo:
        if obj is _MISSING or obj is None:
            return CallInfo(expr, "unresolved")
        if isinstance(obj, _Instance):
            obj = obj.cls
        if isinstance(obj, type):
            init = obj.__dict__.get("__init__")
            code = getattr(init, "__code__", None)
            if code is not None and self.files(code.co_filename):
                fid = self.fn_id_for(code.co_filename, code.co_firstlineno)
                return CallInfo(expr, "user", target=fid)
            lib = module_lib(obj)
            if obj.__module__ == "builtins":
                return CallInfo(expr, "builtin")
            src = _source_file(obj)
            if src and self.files(src):
                return CallInfo(expr, "user", target=None)  # user class w/o custom __init__
            return CallInfo(expr, "stdlib" if lib in _STDLIB_NAMES else "external", lib=lib)
        fn = unwrap_callable(obj)
        code = getattr(fn, "__code__", None)
        if code is not None:
            if self.files(code.co_filename):
                fid = self.fn_id_for(code.co_filename, code.co_firstlineno)
                return CallInfo(expr, "user", target=fid)
            lib = module_lib(fn)
            if lib in _STDLIB_NAMES:
                return CallInfo(expr, "external" if lib in _STDLIB_IO else "stdlib", lib=lib)
            return CallInfo(expr, "external", lib=lib)
        if isinstance(fn, (types.BuiltinFunctionType, types.BuiltinMethodType)) or callable(fn):
            lib = module_lib(fn)
            self_obj = getattr(fn, "__self__", None)
            if lib in (None, "builtins") and (self_obj is None or isinstance(self_obj, types.ModuleType) and self_obj.__name__ == "builtins"):
                return CallInfo(expr, "builtin")
            if isinstance(fn, types.MethodDescriptorType) or type(fn).__name__ in ("method_descriptor", "wrapper_descriptor"):
                owner = getattr(fn, "__objclass__", None)
                lib = module_lib(owner) if owner is not None else lib
                if lib in (None, "builtins"):
                    return CallInfo(expr, "builtin")
            if lib in _STDLIB_NAMES or lib is None:
                return CallInfo(expr, "external" if lib in _STDLIB_IO else "stdlib", lib=lib)
            return CallInfo(expr, "external", lib=lib)
        return CallInfo(expr, "unresolved")

    def classify_call(self, call: ast.Call, ctx: FnContext) -> CallInfo:
        try:
            expr = ast.unparse(call.func)
        except Exception:  # pragma: no cover
            expr = "?"
        if len(expr) > 80:
            expr = expr[:79] + "…"
        try:
            obj = self._eval(call.func, ctx)
        except Exception:
            obj = _MISSING
        return self.classify_obj(obj, expr)

    # -- light local type inference -------------------------------------
    def local_types(self, fn_node: ast.AST, ctx: FnContext) -> dict[str, Any]:
        """name -> class for `x = Cls(...)`, `with Cls() as x`, and annotations."""
        out: dict[str, Any] = {}
        args = getattr(fn_node, "args", None)
        if args is not None:
            for a in list(getattr(args, "posonlyargs", [])) + list(args.args) + list(args.kwonlyargs):
                if a.annotation is not None:
                    t = self._eval(a.annotation, ctx)
                    if isinstance(t, type):
                        out[a.arg] = _Instance(t)
        for node in ast.walk(fn_node):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if isinstance(node.value, ast.Call):
                    t = self._eval(node.value.func, ctx)
                    if isinstance(t, type):
                        out.setdefault(node.targets[0].id, _Instance(t))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                t = self._eval(node.annotation, ctx)
                if isinstance(t, type):
                    out.setdefault(node.target.id, _Instance(t))
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if isinstance(item.optional_vars, ast.Name) and isinstance(item.context_expr, ast.Call):
                        t = self._eval(item.context_expr.func, ctx)
                        if isinstance(t, type):
                            out.setdefault(item.optional_vars.id, _Instance(t))
        return out


class _Instance:
    """Marker: 'an instance of cls' (we never instantiate anything)."""

    __slots__ = ("cls",)

    def __init__(self, cls: type) -> None:
        self.cls = cls


def _source_file(obj: Any) -> Optional[str]:
    mod = sys.modules.get(getattr(obj, "__module__", "") or "")
    return getattr(mod, "__file__", None)
