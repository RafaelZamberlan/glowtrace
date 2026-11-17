"""AST -> human-readable flow graph for a single function.

The graph is *not* a compiler basic-block CFG. It is designed to be read like an
n8n workflow: consecutive "boring" statements are grouped into one ``step``
node, statements that call user code / I/O become ``call`` nodes, and control
structures (if / loop / try / with / match) become their own nodes with labelled
edges.

Every node owns a range of source lines. At runtime we only observe *line
numbers*, so ``FunctionFlow.lines`` maps line -> node index; the overlay module
uses it to turn an observed line sequence into visited nodes and edges.
"""
from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field
from typing import Callable, Optional

# Call classification produced by the resolver.
#   kind: "user" | "external" | "stdlib" | "builtin" | "unresolved"
@dataclass
class CallInfo:
    expr: str
    kind: str
    target: Optional[str] = None  # fn_id when kind == "user"
    lib: Optional[str] = None  # top-level module for external/stdlib
    awaited: bool = False
    line: int = 0

    def to_json(self) -> dict:
        d = {"expr": self.expr, "kind": self.kind, "line": self.line}
        if self.target:
            d["target"] = self.target
        if self.lib:
            d["lib"] = self.lib
        if self.awaited:
            d["awaited"] = True
        return d


@dataclass
class Node:
    idx: int
    kind: str
    label: str
    line: int
    end_line: int
    own: Optional[tuple[int, int]] = None  # line range observed at runtime
    calls: list[CallInfo] = field(default_factory=list)
    watch: list[str] = field(default_factory=list)  # names read -> captured on visit
    assigns: list[str] = field(default_factory=list)  # names written -> captured after
    try_parent: Optional[int] = None  # innermost enclosing try node
    loop_parent: Optional[int] = None  # innermost enclosing loop node
    parent: Optional[int] = None  # innermost enclosing compound node (if/loop/try/with/...)

    def to_json(self) -> dict:
        d = {
            "id": self.idx,
            "kind": self.kind,
            "label": self.label,
            "line": self.line,
            "end_line": self.end_line,
        }
        if self.own is not None:
            d["own"] = [self.own[0], self.own[1]]
        if self.calls:
            d["calls"] = [c.to_json() for c in self.calls]
        if self.watch:
            d["watch"] = self.watch
        if self.assigns:
            d["assigns"] = self.assigns
        if self.try_parent is not None:
            d["try_parent"] = self.try_parent
        if self.loop_parent is not None:
            d["loop_parent"] = self.loop_parent
        if self.parent is not None:
            d["parent"] = self.parent
        return d


@dataclass
class Edge:
    source: int
    target: int
    kind: str  # next | true | false | loop | exit | exception | case | return | break
    label: str = ""

    def to_json(self) -> dict:
        d = {"source": self.source, "target": self.target, "kind": self.kind}
        if self.label:
            d["label"] = self.label
        return d


@dataclass
class FunctionFlow:
    fn_id: str
    qualname: str
    file: str  # absolute path
    rel_file: str
    line: int
    end_line: int
    is_async: bool
    params: list[str]
    source: str
    source_hash: str
    nodes: list[Node]
    edges: list[Edge]
    lines: dict[int, int]
    doc: Optional[str] = None
    source_start: int = 0

    @property
    def start(self) -> int:
        return 0

    @property
    def end(self) -> int:
        return len(self.nodes) - 1

    def to_json(self) -> dict:
        return {
            "id": self.fn_id,
            "qualname": self.qualname,
            "file": self.rel_file,
            "line": self.line,
            "end_line": self.end_line,
            "is_async": self.is_async,
            "params": self.params,
            "doc": self.doc,
            "source": self.source,
            "source_start": self.source_start,
            "source_hash": self.source_hash,
            "nodes": [n.to_json() for n in self.nodes],
            "edges": [e.to_json() for e in self.edges],
        }


# ----------------------------------------------------------------------------
# helpers

_SIMPLE = (
    ast.Assign,
    ast.AugAssign,
    ast.AnnAssign,
    ast.Expr,
    ast.Pass,
    ast.Delete,
    ast.Assert,
    ast.Import,
    ast.ImportFrom,
    ast.Global,
    ast.Nonlocal,
)
if hasattr(ast, "TypeAlias"):
    _SIMPLE = _SIMPLE + (ast.TypeAlias,)

_MAX_GROUP = 8
_LABEL_MAX = 90


def _short(text: str, limit: int = _LABEL_MAX) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - defensive
        return node.__class__.__name__


def _target_names(target: ast.AST) -> list[str]:
    out: list[str] = []
    for n in ast.walk(target):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            out.append(n.id)
        elif isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store):
            # self.total = ... -> capture "self.total"? keep base name readable
            base = n
            parts = []
            while isinstance(base, ast.Attribute):
                parts.append(base.attr)
                base = base.value
            if isinstance(base, ast.Name):
                parts.append(base.id)
                out.append(".".join(reversed(parts)))
    return out


def _read_names(expr: Optional[ast.AST], limit: int = 6) -> list[str]:
    if expr is None:
        return []
    seen: list[str] = []
    for n in ast.walk(expr):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            if n.id not in seen and n.id not in ("True", "False", "None"):
                seen.append(n.id)
        if len(seen) >= limit:
            break
    return seen


def _assigned(stmt: ast.stmt) -> list[str]:
    if isinstance(stmt, ast.Assign):
        out: list[str] = []
        for t in stmt.targets:
            out += _target_names(t)
        return out
    if isinstance(stmt, (ast.AugAssign, ast.AnnAssign)):
        return _target_names(stmt.target)
    return []


def _is_docstring(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _calls_in(node: ast.AST) -> list[tuple[ast.Call, bool]]:
    """Return (call, awaited) pairs in evaluation-ish order, skipping nested defs."""
    out: list[tuple[ast.Call, bool]] = []
    awaited_ids: set[int] = set()

    def visit(n: ast.AST) -> None:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            return
        if isinstance(n, ast.Await) and isinstance(n.value, ast.Call):
            awaited_ids.add(id(n.value))
        if isinstance(n, ast.Call):
            out.append((n, False))
        for child in ast.iter_child_nodes(n):
            visit(child)

    visit(node)
    return [(c, id(c) in awaited_ids) for c, _ in out]


def _header_range(stmt: ast.stmt, body: list[ast.stmt]) -> tuple[int, int]:
    first_body = body[0].lineno if body else stmt.lineno + 1
    return stmt.lineno, max(stmt.lineno, first_body - 1)


def _signature(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, list[str]]:
    a = fn.args
    params = [p.arg for p in getattr(a, "posonlyargs", [])] + [p.arg for p in a.args]
    if a.vararg:
        params.append("*" + a.vararg.arg)
    params += [p.arg for p in a.kwonlyargs]
    if a.kwarg:
        params.append("**" + a.kwarg.arg)
    prefix = "async def " if isinstance(fn, ast.AsyncFunctionDef) else "def "
    return prefix + f"{fn.name}({', '.join(params)})", params


Classifier = Callable[[ast.Call, bool], CallInfo]


class _LoopCtx:
    __slots__ = ("head", "breaks")

    def __init__(self, head: int) -> None:
        self.head = head
        self.breaks: list[tuple[int, str, str]] = []


class _Builder:
    def __init__(
        self,
        fn: ast.FunctionDef | ast.AsyncFunctionDef,
        classify: Classifier,
    ) -> None:
        self.fn = fn
        self.classify = classify
        self.nodes: list[Node] = []
        self.edges: list[Edge] = []
        self.loops: list[_LoopCtx] = []
        self.trys: list[int] = []
        self.handlers: list[list[int]] = []  # handler node idxs per try on stack
        self.finallies: list[int] = []  # finally nodes of enclosing try statements
        self.struct: list[int] = []  # enclosing compound nodes
        self.returns: list[int] = []

    # -- primitives -------------------------------------------------------
    def add(
        self,
        kind: str,
        label: str,
        line: int,
        end_line: Optional[int] = None,
        own: Optional[tuple[int, int]] = None,
        **kw,
    ) -> int:
        idx = len(self.nodes)
        node = Node(
            idx=idx,
            kind=kind,
            label=_short(label),
            line=line,
            end_line=end_line if end_line is not None else line,
            own=own,
            try_parent=self.trys[-1] if self.trys else None,
            loop_parent=self.loops[-1].head if self.loops else None,
            parent=self.struct[-1] if self.struct else None,
            **kw,
        )
        self.nodes.append(node)
        return idx

    def nested(self, idx: int, stmts: list[ast.stmt], preds):
        """Build a body whose nodes are structurally inside compound node idx."""
        self.struct.append(idx)
        try:
            return self.block(stmts, preds)
        finally:
            self.struct.pop()

    def link(self, preds: list[tuple[int, str, str]], target: int) -> None:
        for src, kind, label in preds:
            self.edges.append(Edge(src, target, kind, label))

    def calls_of(self, node: ast.AST) -> list[CallInfo]:
        infos = []
        for call, awaited in _calls_in(node):
            info = self.classify(call, awaited)
            info.awaited = awaited
            info.line = call.lineno
            infos.append(info)
        return infos

    @staticmethod
    def _interesting(calls: list[CallInfo]) -> list[CallInfo]:
        return [c for c in calls if c.kind in ("user", "external") or c.awaited]

    # -- build ------------------------------------------------------------
    def build(self) -> tuple[list[Node], list[Edge]]:
        sig, _ = _signature(self.fn)
        start = self.add("start", sig, self.fn.lineno)
        body = list(self.fn.body)
        if body and _is_docstring(body[0]):
            body = body[1:]
        outs = self.block(body, [(start, "next", "")])
        end_line = getattr(self.fn, "end_lineno", self.fn.lineno) or self.fn.lineno
        end = self.add("end", "fim", end_line)
        self.link(outs, end)
        for r in self.returns:
            self.edges.append(Edge(r, end, "return", ""))
        return self.nodes, self.edges

    def block(self, stmts: list[ast.stmt], preds: list[tuple[int, str, str]]):
        group: list[ast.stmt] = []
        group_calls: list[CallInfo] = []
        for s in stmts:
            if isinstance(s, _SIMPLE) and not _is_docstring(s):
                calls = self.calls_of(s)
                interesting = self._interesting(calls)
                if not interesting:
                    group.append(s)
                    group_calls += calls
                    if len(group) >= _MAX_GROUP:
                        preds = self.flush(group, group_calls, preds)
                        group, group_calls = [], []
                    continue
                preds = self.flush(group, group_calls, preds)
                group, group_calls = [], []
                preds = self.call_stmt(s, calls, preds)
                continue
            if _is_docstring(s):
                continue
            preds = self.flush(group, group_calls, preds)
            group, group_calls = [], []
            preds = self.stmt(s, preds)
        preds = self.flush(group, group_calls, preds)
        return preds

    def flush(self, group, calls, preds):
        if not group:
            return preds
        first, last = group[0], group[-1]
        label = _unparse(first)
        if len(group) > 1:
            label = _short(label, 70) + f"  (+{len(group) - 1})"
        assigns: list[str] = []
        for s in group:
            for n in _assigned(s):
                if n not in assigns:
                    assigns.append(n)
        idx = self.add(
            "step",
            label,
            first.lineno,
            last.end_lineno,
            own=(first.lineno, last.end_lineno or first.lineno),
            assigns=assigns[:8],
            calls=[c for c in calls if c.kind != "builtin"][:8],
        )
        self.link(preds, idx)
        return [(idx, "next", "")]

    def call_stmt(self, s: ast.stmt, calls: list[CallInfo], preds):
        idx = self.add(
            "call",
            _unparse(s),
            s.lineno,
            s.end_lineno,
            own=(s.lineno, s.end_lineno or s.lineno),
            calls=self._interesting(calls) + [c for c in calls if c not in self._interesting(calls) and c.kind != "builtin"][:4],
            assigns=_assigned(s),
        )
        self.link(preds, idx)
        return [(idx, "next", "")]

    # -- statements ---------------------------------------------------------
    def stmt(self, s: ast.stmt, preds):
        method = getattr(self, "s_" + s.__class__.__name__, None)
        if method is None:
            # unknown/compound statement we don't model: single opaque step
            idx = self.add(
                "step",
                _unparse(s).split("\n")[0],
                s.lineno,
                s.end_lineno,
                own=(s.lineno, s.end_lineno or s.lineno),
            )
            self.link(preds, idx)
            return [(idx, "next", "")]
        return method(s, preds)

    def s_Return(self, s: ast.Return, preds):
        calls = self.calls_of(s) if s.value is not None else []
        idx = self.add(
            "return",
            _unparse(s),
            s.lineno,
            s.end_lineno,
            own=(s.lineno, s.end_lineno or s.lineno),
            calls=[c for c in calls if c.kind != "builtin"],
            watch=_read_names(s.value, 4),
        )
        self.link(preds, idx)
        self.returns.append(idx)
        return []

    def s_Raise(self, s: ast.Raise, preds):
        calls = self.calls_of(s)
        idx = self.add(
            "raise",
            _unparse(s),
            s.lineno,
            s.end_lineno,
            own=(s.lineno, s.end_lineno or s.lineno),
            calls=[c for c in calls if c.kind in ("user", "external")],
        )
        self.link(preds, idx)
        if self.handlers and self.handlers[-1]:
            for h in self.handlers[-1]:
                self.edges.append(Edge(idx, h, "exception", ""))
        if self.finallies:
            self.edges.append(Edge(idx, self.finallies[-1], "exception", ""))
        return []

    def s_If(self, s: ast.If, preds, is_elif: bool = False):
        kw = "elif" if is_elif else "if"
        idx = self.add(
            "if",
            f"{kw} {_unparse(s.test)}",
            s.lineno,
            own=_header_range(s, s.body),
            calls=[c for c in self.calls_of(s.test) if c.kind != "builtin"],
            watch=_read_names(s.test),
        )
        self.link(preds, idx)
        out = self.nested(idx, s.body, [(idx, "true", "sim")])
        if s.orelse:
            first = s.orelse[0]
            if len(s.orelse) == 1 and isinstance(first, ast.If) and self._is_elif(first):
                out += self.s_If(first, [(idx, "false", "não")], is_elif=True)
            else:
                out += self.nested(idx, s.orelse, [(idx, "false", "não")])
        else:
            out.append((idx, "false", "não"))
        return out

    _src_lines: list[str] = []

    def _is_elif(self, node: ast.If) -> bool:
        try:
            text = self._src_lines[node.lineno - 1][node.col_offset : node.col_offset + 4]
            return text == "elif"
        except Exception:
            return False

    def _loop(self, s, label, preds, watch, assigns, infinite=False):
        idx = self.add(
            "loop",
            label,
            s.lineno,
            own=_header_range(s, s.body),
            watch=watch,
            assigns=assigns,
            calls=[c for c in self.calls_of(getattr(s, "iter", None) or s.test) if c.kind != "builtin"],
        )
        self.link(preds, idx)
        ctx = _LoopCtx(idx)
        self.loops.append(ctx)
        body_out = self.nested(idx, s.body, [(idx, "true", "cada" if not isinstance(s, ast.While) else "sim")])
        self.loops.pop()
        for src, _kind, _label in body_out:
            self.edges.append(Edge(src, idx, "loop", ""))
        exits: list[tuple[int, str, str]] = [] if infinite else [(idx, "exit", "fim")]
        if s.orelse:
            exits = self.block(s.orelse, exits)
        return exits + ctx.breaks

    def s_For(self, s: ast.For, preds):
        names = _target_names(s.target)
        return self._loop(
            s, f"for {_unparse(s.target)} in {_unparse(s.iter)}", preds, [], names
        )

    def s_AsyncFor(self, s, preds):
        names = _target_names(s.target)
        return self._loop(
            s, f"async for {_unparse(s.target)} in {_unparse(s.iter)}", preds, [], names
        )

    def s_While(self, s: ast.While, preds):
        infinite = isinstance(s.test, ast.Constant) and bool(s.test.value)
        return self._loop(
            s, f"while {_unparse(s.test)}", preds, _read_names(s.test), [], infinite=infinite
        )

    def s_Break(self, s, preds):
        idx = self.add("break", "break", s.lineno, own=(s.lineno, s.lineno))
        self.link(preds, idx)
        if self.loops:
            self.loops[-1].breaks.append((idx, "break", ""))
        return []

    def s_Continue(self, s, preds):
        idx = self.add("continue", "continue", s.lineno, own=(s.lineno, s.lineno))
        self.link(preds, idx)
        if self.loops:
            self.edges.append(Edge(idx, self.loops[-1].head, "loop", ""))
        return []

    def _try(self, s, preds, star=False):
        idx = self.add("try", "try", s.lineno, own=(s.lineno, s.lineno))
        self.link(preds, idx)
        # pre-create handler and finally nodes so raises inside can link to them
        handler_nodes: list[int] = []
        self.trys.append(idx)
        self.struct.append(idx)
        for h in s.handlers:
            typ = _unparse(h.type) if h.type is not None else ""
            label = ("except* " if star else "except ") + typ
            if h.name:
                label += f" as {h.name}"
            hidx = self.add(
                "except",
                label.strip(),
                h.lineno,
                own=_header_range(h, h.body),
                assigns=[h.name] if h.name else [],
            )
            self.nodes[hidx].try_parent = idx
            handler_nodes.append(hidx)
            self.edges.append(Edge(idx, hidx, "exception", "erro"))
        fidx = None
        if s.finalbody:
            fidx = self.add("finally", "finally", s.finalbody[0].lineno)
        self.struct.pop()
        # a handler whose type does not match falls through to the next one,
        # and the last one re-raises through finally
        for a, b in zip(handler_nodes, handler_nodes[1:]):
            self.edges.append(Edge(a, b, "false", "não"))
        if handler_nodes and fidx is not None:
            self.edges.append(Edge(handler_nodes[-1], fidx, "exception", ""))
        if fidx is not None:
            self.finallies.append(fidx)
        self.handlers.append(handler_nodes)
        body_out = self.nested(idx, s.body, [(idx, "next", "")])
        self.handlers.pop()
        self.trys.pop()
        handlers_out: list[tuple[int, str, str]] = []
        for h, hidx in zip(s.handlers, handler_nodes):
            handlers_out += self.nested(hidx, h.body, [(hidx, "next", "")])
        if s.orelse:
            body_out = self.nested(idx, s.orelse, body_out)
        if fidx is not None:
            self.finallies.pop()
        out = body_out + handlers_out
        if fidx is not None:
            self.link(out, fidx)
            # a return inside the try also runs finally; we keep return -> end edges
            out = self.nested(fidx, s.finalbody, [(fidx, "next", "")])
        return out

    def s_Try(self, s, preds):
        return self._try(s, preds)

    def s_TryStar(self, s, preds):  # Python 3.11+
        return self._try(s, preds, star=True)

    def _with(self, s, preds, is_async):
        items = ", ".join(_unparse(i) for i in s.items)
        names: list[str] = []
        calls: list[CallInfo] = []
        for item in s.items:
            if item.optional_vars is not None:
                names += _target_names(item.optional_vars)
            calls += self.calls_of(item.context_expr)
        idx = self.add(
            "with",
            ("async with " if is_async else "with ") + items,
            s.lineno,
            own=_header_range(s, s.body),
            assigns=names,
            calls=[c for c in calls if c.kind != "builtin"],
        )
        self.link(preds, idx)
        return self.nested(idx, s.body, [(idx, "next", "")])

    def s_With(self, s, preds):
        return self._with(s, preds, False)

    def s_AsyncWith(self, s, preds):
        return self._with(s, preds, True)

    def s_Match(self, s, preds):
        idx = self.add(
            "match",
            f"match {_unparse(s.subject)}",
            s.lineno,
            own=(s.lineno, s.cases[0].pattern.lineno - 1 if s.cases else s.lineno),
            watch=_read_names(s.subject),
        )
        self.link(preds, idx)
        out: list[tuple[int, str, str]] = []
        has_wildcard = False
        prev = idx
        for case in s.cases:
            pat = _unparse(case.pattern)
            if isinstance(case.pattern, ast.MatchAs) and case.pattern.pattern is None and case.guard is None:
                has_wildcard = True
            label = f"case {pat}" + (f" if {_unparse(case.guard)}" if case.guard is not None else "")
            cidx = self.add(
                "case",
                label,
                case.pattern.lineno,
                own=(case.pattern.lineno, max(case.pattern.lineno, case.body[0].lineno - 1)),
            )
            self.edges.append(Edge(prev, cidx, "case" if prev == idx else "false", pat if prev == idx else "não"))
            out += self.nested(cidx, case.body, [(cidx, "true", "sim")])
            prev = cidx
        if not has_wildcard:
            out.append((prev, "false", "nenhum"))
        return out

    def _def(self, s, preds):
        label = ("class " if isinstance(s, ast.ClassDef) else "def ") + s.name
        line = s.decorator_list[0].lineno if getattr(s, "decorator_list", None) else s.lineno
        idx = self.add("step", label, line, s.end_lineno, own=(line, s.lineno))
        self.link(preds, idx)
        return [(idx, "next", "")]

    s_FunctionDef = _def
    s_AsyncFunctionDef = _def
    s_ClassDef = _def


def build_flow(
    fn_node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    fn_id: str,
    qualname: str,
    file: str,
    rel_file: str,
    source_lines: list[str],
    classify: Optional[Classifier] = None,
) -> FunctionFlow:
    classify = classify or (lambda call, awaited: CallInfo(_unparse(call.func), "unresolved"))
    builder = _Builder(fn_node, classify)
    builder._src_lines = source_lines
    nodes, edges = builder.build()

    start_line = fn_node.decorator_list[0].lineno if fn_node.decorator_list else fn_node.lineno
    end_line = fn_node.end_lineno or fn_node.lineno
    source = "\n".join(source_lines[start_line - 1 : end_line])
    _, params = _signature(fn_node)

    lines: dict[int, int] = {}
    for n in nodes:
        if n.own is None:
            continue
        a, b = n.own
        for ln in range(a, b + 1):
            lines.setdefault(ln, n.idx)

    return FunctionFlow(
        fn_id=fn_id,
        qualname=qualname,
        file=file,
        rel_file=rel_file,
        line=fn_node.lineno,
        end_line=end_line,
        is_async=isinstance(fn_node, ast.AsyncFunctionDef),
        params=params,
        source=source,
        source_hash=hashlib.sha1(source.encode("utf-8", "replace")).hexdigest()[:12],
        nodes=nodes,
        edges=edges,
        lines=lines,
        doc=ast.get_docstring(fn_node),
        source_start=start_line,
    )
