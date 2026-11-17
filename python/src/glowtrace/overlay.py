"""Overlay a recorded execution on the static flow graphs.

Input: frames with ``path`` = ordered node indexes visited (from line events).
Output per frame: visited node counts, traversed edge counts, the error node,
and which node of the parent frame made the call.

Consecutive visits (a, b) are connected by the shortest static path from a to b
whose intermediate nodes never emit line events themselves (start, finally,
end...). If none exists (e.g. an exception jumped into an ``except``), we fall
back to the exception edge of the enclosing ``try``, or record a "jump".
"""
from __future__ import annotations

from collections import deque
from typing import Optional

from .static.flow import FunctionFlow
from .static.registry import Registry

_SILENT = {"start", "end", "finally"}


class _Graph:
    def __init__(self, flow: FunctionFlow) -> None:
        self.flow = flow
        self.out: dict[int, list[tuple[int, int]]] = {}
        for i, e in enumerate(flow.edges):
            self.out.setdefault(e.source, []).append((e.target, i))
        self._cache: dict[tuple[int, int], Optional[list[int]]] = {}

    def path(self, a: int, b: int) -> Optional[list[int]]:
        key = (a, b)
        if key in self._cache:
            return self._cache[key]
        res = self._bfs(a, b, strict=True) or self._bfs(a, b, strict=False, max_depth=3)
        self._cache[key] = res
        return res

    def _bfs(self, a: int, b: int, strict: bool, max_depth: int = 8) -> Optional[list[int]]:
        nodes = self.flow.nodes
        q: deque[tuple[int, list[int]]] = deque([(a, [])])
        seen = {a}
        while q:
            cur, edges = q.popleft()
            if len(edges) >= max_depth:
                continue
            for nxt, ei in self.out.get(cur, ()):
                if nxt == b:
                    return edges + [ei]
                if nxt in seen:
                    continue
                if strict and nodes[nxt].kind not in _SILENT and nodes[nxt].own is not None:
                    continue
                seen.add(nxt)
                q.append((nxt, edges + [ei]))
        return None

    def is_block_exit(self, a: int, b: int) -> bool:
        """b is a `with` statement that structurally encloses a."""
        nodes = self.flow.nodes
        if nodes[b].kind != "with":
            return False
        cur = nodes[a].parent
        guard = 0
        while cur is not None and guard < 64:
            if cur == b:
                return True
            cur = nodes[cur].parent
            guard += 1
        return False

    def exception_edge(self, a: int, b: int) -> Optional[int]:
        """Edge try->except when b is a handler of a try enclosing a."""
        nodes = self.flow.nodes
        target = nodes[b]
        if target.kind != "except" or target.try_parent is None:
            return None
        t = target.try_parent
        cur: Optional[int] = a
        guard = 0
        while cur is not None and guard < 64:
            if nodes[cur].try_parent == t or cur == t:
                for nxt, ei in self.out.get(t, ()):
                    if nxt == b:
                        return ei
            cur = nodes[cur].try_parent
            guard += 1
        # still accept it: python only jumps to a handler from inside its try
        for nxt, ei in self.out.get(t, ()):
            if nxt == b:
                return ei
        return None


def overlay_execution(execution: dict, registry: Registry) -> dict:
    graphs: dict[str, Optional[_Graph]] = {}
    frames = execution.get("frames", [])
    by_id = {f["id"]: f for f in frames}
    out_frames = []
    for fr in frames:
        fid = fr["fn"]
        if fid not in graphs:
            flow = registry.flow(fid)
            graphs[fid] = _Graph(flow) if flow else None
        g = graphs[fid]
        info: dict = {"id": fr["id"]}
        if g is None:
            info["missing"] = True
            out_frames.append(info)
            continue
        flow = g.flow
        info["stale"] = bool(fr.get("hash") and fr["hash"] != flow.source_hash)
        visits: dict[int, int] = {flow.start: 1}
        edges: dict[int, int] = {}
        jumps: list[list[int]] = []
        seq = [flow.start] + [p[0] for p in fr.get("path", [])]
        a = seq[0]
        for b in seq[1:]:
            if b >= len(flow.nodes):
                continue
            if g.is_block_exit(a, b):
                continue  # `with` header re-executed to run __exit__: not a new visit
            p = g.path(a, b)
            visits[b] = visits.get(b, 0) + 1
            if p is None:
                ei = g.exception_edge(a, b)
                p = [ei] if ei is not None else None
            if p is None:
                jumps.append([a, b])
                a = b
                continue
            for ei in p:
                edges[ei] = edges.get(ei, 0) + 1
                tgt = flow.edges[ei].target
                if tgt != b:
                    visits[tgt] = visits.get(tgt, 0) + 1
            a = b
        for k, v in (fr.get("overflow") or {}).items():
            visits[int(k)] = visits.get(int(k), 0) + v
        last = a
        if "exception" in fr:
            info["error_node"] = last
        elif not fr.get("incomplete"):
            p = g.path(last, flow.end)
            if p is not None:
                for ei in p:
                    edges[ei] = edges.get(ei, 0) + 1
                    tgt = flow.edges[ei].target
                    visits[tgt] = visits.get(tgt, 0) + 1
            else:
                visits[flow.end] = visits.get(flow.end, 0) + 1
        info["visits"] = {str(k): v for k, v in visits.items()}
        info["edges"] = {str(k): v for k, v in edges.items()}
        if jumps:
            info["jumps"] = jumps
        # which node in the parent made this call
        parent = by_id.get(fr.get("parent"))
        if parent is not None and fr.get("call_line"):
            pflow = registry.flow(parent["fn"])
            if pflow is not None:
                node = pflow.lines.get(fr["call_line"])
                if node is not None:
                    info["call_node"] = node
        out_frames.append(info)
    return {"frames": out_frames}
