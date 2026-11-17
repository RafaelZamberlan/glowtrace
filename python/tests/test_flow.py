"""Static flow graph construction."""
import ast
import textwrap

from glowtrace.static.flow import build_flow


def flow_of(src: str):
    src = textwrap.dedent(src)
    tree = ast.parse(src)
    fn = tree.body[0]
    return build_flow(fn, fn_id="t::f", qualname="f", file="t.py", rel_file="t.py", source_lines=src.splitlines())


def kinds(fl):
    return [n.kind for n in fl.nodes]


def edge(fl, a_label_prefix, b_label_prefix):
    a = next(n.idx for n in fl.nodes if n.label.startswith(a_label_prefix))
    b = next(n.idx for n in fl.nodes if n.label.startswith(b_label_prefix))
    return [e for e in fl.edges if e.source == a and e.target == b]


def test_groups_simple_statements_into_one_step():
    fl = flow_of(
        """
        def f(x):
            a = 1
            b = 2
            c = a + b
            return c
        """
    )
    assert kinds(fl) == ["start", "step", "return", "end"]
    assert fl.nodes[1].assigns == ["a", "b", "c"]
    assert fl.nodes[1].label.endswith("(+2)")


def test_if_elif_else_edges():
    fl = flow_of(
        """
        def f(x):
            if x > 10:
                y = 'big'
            elif x > 5:
                y = 'mid'
            else:
                y = 'small'
            return y
        """
    )
    assert [n.label for n in fl.nodes if n.kind == "if"] == ["if x > 10", "elif x > 5"]
    assert edge(fl, "if x > 10", "y = 'big'")[0].kind == "true"
    assert edge(fl, "if x > 10", "elif x > 5")[0].kind == "false"
    assert edge(fl, "elif x > 5", "y = 'small'")[0].kind == "false"
    assert fl.nodes[next(n.idx for n in fl.nodes if n.kind == "if")].watch == ["x"]


def test_loops_break_continue():
    fl = flow_of(
        """
        def f(items):
            for it in items:
                if it is None:
                    continue
                if it < 0:
                    break
                total = it
            while True:
                break
            return 1
        """
    )
    loop = next(n for n in fl.nodes if n.label.startswith("for it"))
    assert loop.assigns == ["it"]
    back = [e for e in fl.edges if e.target == loop.idx and e.kind == "loop"]
    assert len(back) == 2  # body end + continue
    wh = next(n for n in fl.nodes if n.label.startswith("while True"))
    assert not [e for e in fl.edges if e.source == wh.idx and e.kind == "exit"]  # infinite loop: only break exits


def test_try_except_finally_and_raise_links_to_handler():
    fl = flow_of(
        """
        def f(x):
            try:
                if x:
                    raise ValueError('x')
                y = 1
            except ValueError as e:
                y = 2
            finally:
                z = 3
            return y
        """
    )
    exc = next(n for n in fl.nodes if n.kind == "except")
    assert exc.label == "except ValueError as e"
    raise_node = next(n for n in fl.nodes if n.kind == "raise")
    assert any(e.source == raise_node.idx and e.target == exc.idx and e.kind == "exception" for e in fl.edges)
    assert any(n.kind == "finally" for n in fl.nodes)


def test_match_cases():
    fl = flow_of(
        """
        def f(cmd):
            match cmd:
                case 'a':
                    return 1
                case 'b' | 'c':
                    return 2
            return 0
        """
    )
    assert [n.label for n in fl.nodes if n.kind == "case"] == ["case 'a'", "case 'b' | 'c'"]
    last_case = [n for n in fl.nodes if n.kind == "case"][-1]
    assert any(e.source == last_case.idx and e.label == "nenhum" for e in fl.edges)


def test_with_and_await_call_nodes():
    fl = flow_of(
        """
        async def f(client):
            async with lock:
                r = await client.get('/x')
            data = r.json()
            return data
        """
    )
    assert kinds(fl)[:3] == ["start", "with", "call"]
    call = fl.nodes[2]
    assert call.calls[0].awaited is True


def test_line_index_covers_headers_and_bodies():
    fl = flow_of(
        """
        def f(x):
            if (x and
                    x > 1):
                return 1
            return 2
        """
    )
    if_node = next(n for n in fl.nodes if n.kind == "if")
    assert fl.lines[3] == if_node.idx and fl.lines[4] == if_node.idx


def test_raise_and_unmatched_except_reach_finally():
    fl = flow_of(
        """
        def f(x):
            try:
                if x:
                    raise ValueError()
                y = 1
            except KeyError:
                y = 2
            finally:
                z = 3
            return y
        """
    )
    fin = next(n for n in fl.nodes if n.kind == "finally")
    exc = next(n for n in fl.nodes if n.kind == "except")
    rais = next(n for n in fl.nodes if n.kind == "raise")
    assert any(e.source == rais.idx and e.target == fin.idx for e in fl.edges)
    assert any(e.source == exc.idx and e.target == fin.idx for e in fl.edges)
    inner = next(n for n in fl.nodes if n.label == "z = 3")
    assert inner.parent == fin.idx


def test_with_exit_is_not_a_jump():
    """Python re-executes the `with` line to call __exit__; overlay must not flag it."""
    import contextlib

    from glowtrace.overlay import _Graph

    fl = flow_of(
        """
        def f(items):
            for it in items:
                with ctx() as c:
                    v = c + it
            return 1
        """
    )
    g = _Graph(fl)
    w = next(n for n in fl.nodes if n.kind == "with")
    body = next(n for n in fl.nodes if n.label.startswith("v = c"))
    assert body.parent == w.idx
    assert g.is_block_exit(body.idx, w.idx)
