# Runtime instrumentation for per-request execution-flow recording (Python, Java, Node.js), as of November 2026

Scope note: these notes cover the mechanisms for recording function calls, arguments, return values, exceptions and the if/else/loop branch taken, per HTTP request, at low overhead. Facts carry inline sources. Bullets under "Inferences" are engineering judgment or standard-API knowledge that was **not** re-verified in this session; they are marked so the report writer can soften or drop them.

---

## 1. Python `sys.monitoring` (PEP 669): API surface, events, and what changed in 3.12, 3.13 and 3.14

### Takeaway
`sys.monitoring` is the right base for a Python recorder on 3.12+. Python 3.14 (October 2025) is the first version with usable branch events: `BRANCH_LEFT`/`BRANCH_RIGHT` replace the deprecated `BRANCH` and can be disabled independently. Branch events report bytecode offsets `(code, src_offset, dest_offset)`. Map them to source *locations* (`co_positions`), not to the offsets themselves, because CPython core developers treat offsets as an implementation detail.

### Cited Findings
**Module, tool IDs, lifecycle**
- `sys.monitoring` was added in Python 3.12. It is a namespace inside `sys`, so `import sys.monitoring` raises `ModuleNotFoundError`. — [Python 3.14 docs: sys.monitoring](https://docs.python.org/3.14/library/sys.monitoring.html)
- Tool IDs are integers 0–5. Predefined IDs are `DEBUGGER_ID=0`, `COVERAGE_ID=1`, `PROFILER_ID=2` and `OPTIMIZER_ID=5`; 3 and 4 are unassigned. The VM treats all IDs alike, and "tools currently cannot monitor each other", so a recorder's own callbacks do not generate events for itself or for other tools. — [docs](https://docs.python.org/3.14/library/sys.monitoring.html)
- `use_tool_id(tool_id, name)` raises `ValueError` if the ID is taken, and `get_tool(id)` returns the name or `None`. `clear_tool_id()` was **added in 3.14**. **In 3.14** `free_tool_id()` calls `clear_tool_id()` first; before 3.14 it neither disabled events nor unregistered callbacks. — [docs](https://docs.python.org/3.14/library/sys.monitoring.html)
- Coverage.py 7.14.2 (2026-06-20) fixed a bug where "we were assuming we could use the `COVERAGE_ID` tool id"; it now searches for a free ID. A recorder that coexists with coverage, debuggers or profilers should do the same. — [coverage.py changelog](https://coverage.readthedocs.io/en/latest/changes.html)
- Events and callbacks are **per interpreter, not per thread**, unlike `sys.settrace()`. When the active event set changes, "the VM will immediately update all code objects present on the call stack of any thread". The PEP describes no per-thread enabling. — [PEP 669](https://peps.python.org/pep-0669/)
- `sys.settrace`/`sys.setprofile` behave "as if they were tools 6 and 7" and can run alongside `sys.monitoring` tools. — [PEP 669](https://peps.python.org/pep-0669/)

**Events (3.14 docs)**
- **Local events**, which can be enabled per code object and disabled per location: `PY_START`, `PY_RESUME`, `PY_RETURN`, `PY_YIELD`, `CALL`, `LINE`, `INSTRUCTION`, `JUMP`, `BRANCH_LEFT`, `BRANCH_RIGHT`, `STOP_ITERATION`. — [docs](https://docs.python.org/3.14/library/sys.monitoring.html)
- **Other events**, which cannot be disabled per location: `PY_THROW`, `PY_UNWIND`, `RAISE`, `EXCEPTION_HANDLED`. **Ancillary events** `C_RAISE` and `C_RETURN` are seen only when `CALL` is monitored. `RERAISE` also exists. — [docs](https://docs.python.org/3.14/library/sys.monitoring.html)
- `BRANCH` is **deprecated in 3.14**. The docs recommend `BRANCH_LEFT`/`BRANCH_RIGHT` because they "can be disabled independently", which gives much better performance. The docs do not say which side is "left" and which is "right", only that the mapping is consistent for the program's duration. — [docs](https://docs.python.org/3.14/library/sys.monitoring.html)
- `STOP_ITERATION` lets tools monitor real exceptions without slowing generators and coroutines, and unlike `RAISE` it can be disabled locally. — [docs](https://docs.python.org/3.14/library/sys.monitoring.html)
- Callback signatures (3.14):
  - `PY_START`, `PY_RESUME`: `(code, instruction_offset)`
  - `PY_RETURN`, `PY_YIELD`: `(code, instruction_offset, retval)`
  - `CALL`, `C_RAISE`, `C_RETURN`: `(code, instruction_offset, callable, arg0)`, where `arg0` is `sys.monitoring.MISSING` if there are no arguments and is the instance for bound methods
  - `RAISE`, `RERAISE`, `EXCEPTION_HANDLED`, `PY_UNWIND`, `PY_THROW`, `STOP_ITERATION`: `(code, instruction_offset, exception)`
  - `LINE`: `(code, line_number)`
  - `BRANCH_LEFT`, `BRANCH_RIGHT`, `JUMP`: `(code, instruction_offset, destination_offset)`
  - `INSTRUCTION`: `(code, instruction_offset)`

  — [docs](https://docs.python.org/3.14/library/sys.monitoring.html)
- `set_events(tool, events)` sets global events. `set_local_events(tool, code, events)` sets per-code-object events. "Local events add to global events, but do not mask them." An event that is enabled both globally and locally fires only once. — [docs](https://docs.python.org/3.14/library/sys.monitoring.html); [PEP 669](https://peps.python.org/pep-0669/)
- **`DISABLE`:** returning `sys.monitoring.DISABLE` from a callback disables that event "for the current code location only". Only local events can be disabled. The docs say returning `DISABLE` from a callback for a global (non-local) event makes the interpreter raise `ValueError` with no traceback. Any other return value is ignored. `restart_events()` re-enables everything that `DISABLE` turned off, **for all tools**. — [docs](https://docs.python.org/3.14/library/sys.monitoring.html)
- Cost model in the PEP: `set_local_events` is "slower, but not especially so". `use_tool_id`, `free_tool_id`, `set_events` and `restart_events` "should be regarded as slow". — [PEP 669](https://peps.python.org/pep-0669/)
- Mechanism: instrumentation builds on 3.11 quickening, with bytecodes replaced by instrumented variants (for example `CALL` becomes `INSTRUMENTED_CALL`). The PEP notes "this will interfere with specialization, which will result in some performance degradation". `RAISE`-type events are cheap to toggle because they do not rely on code instrumentation. — [PEP 669](https://peps.python.org/pep-0669/)

**Why branch events changed in 3.14**
- On 3.12 and 3.13, disabling a `BRANCH` event disables the whole *source* offset, so a tool never hears about the other destination. Ned Batchelder: "The problem is that disabling a branch event disables the source offset." SlipCover's workaround inserted no-op lines at branch destinations and listened only to `LINE`. — [Ned Batchelder, "Pushing back on sys.monitoring" (Jul 2024)](https://nedbatchelder.com/blog/202407/pushing_back_on_sysmonitoring)
- The redesign was discussed on discuss.python.org (July 2024). The goal was per-(source, destination) disabling. Mark Shannon proposed inserting NOPs on not-taken paths that emit "branch not taken" events. The first experiment slowed the plain interpreter by about 0.5–1%. A tweaked version was "in the noise, but probably < 0.5%". With the JIT eliminating NOPs in hot code he estimated "<0.1%". — [discuss.python.org thread](https://discuss.python.org/t/updating-sys-monitoring-how-branch-events-are-disabled/59527)
- Coverage.py 7.7.0 (2025-03-16): sysmon "now works for branch coverage if you are using Python 3.14.0 alpha 6 or newer". — [changelog](https://coverage.readthedocs.io/en/latest/changes.html)

**Mapping branch offsets to source**
- CPython issue gh-122762 ("Better mapping of sys.monitoring branches back to source code") contains these points:
  - Mark Shannon: offsets "should be regarded as an implementation detail. It is the locations that matter."
  - He also wrote: "any branch that exits the scope must have `destination_location == source_location`."
  - `co_positions()` gives each instruction's start/end line and column, and `co_lines()` gives the lines that contain code.
  - If a destination has no location, or the same location as the source, "you'll need to look at the next instruction to find a new location". Ned Batchelder mapped branches by walking the instruction trail from each destination until a new line appeared.
  - Irit Katriel cautioned: "The structure of the AST is not stable."
  - The issue was still open with no code change recorded.

  — [cpython#122762](https://github.com/python/cpython/issues/122762)
- `code.co_branches()` was added by Mark Shannon in draft PR #122564 (Aug 2024). It returns an iterator of 3-tuples `(start, not_taken, taken)` of byte offsets, and Ned used it on 3.14.0a3+ dev builds. The issue does not say whether it is public or documented. — [cpython#122762](https://github.com/python/cpython/issues/122762); [PR #122564](https://github.com/python/cpython/pull/122564)
- A 3.14 fix for `async for` branch monitoring (GH-128534) made both branches of a pair share a common source and appear in `co_branches`. This was found in search snippets of CPython commits only, not verified in a primary page. — [search-derived; cpython commit log mirror](https://remotebranch.eu/Stowage/cpython/commits/branch/3.14/Lib/test/test_monitoring.py)
- Ned Batchelder described moving coverage.py from "arcs" (line-pair transitions) to branches, noting that `code.co_branches()` "might make it all obsolete over time". — [Coverage branches instead of arcs (Aug 2024)](https://nedbatchelder.com/blog/202408/coverage_branches_instead_of_arcs.html)

### Inferences
- **Version matrix for a recorder** (unverified engineering summary):
  - 3.12/3.13: use `BRANCH` + `JUMP`. Branch recording works, but you must not `DISABLE` user-code branch locations, which a per-request recorder never wants to do anyway.
  - 3.14+: use `BRANCH_LEFT | BRANCH_RIGHT | JUMP`.
  - Earlier than 3.12: see section 3.
- You do not need to know which side is "left" and which is "right". `destination_offset` is delivered with the event. Precompute, per code object, `src_offset -> {dest_offset: (kind, ast_node_id)}` from `co_branches()` on 3.14, or from `dis.get_instructions()` on 3.12/3.13 (look for `POP_JUMP_IF_*`, `FOR_ITER`, `SEND`), then resolve each destination to a source location with `co_positions()`.
- Per PEP 657 (not re-fetched), the tuples are `(lineno, end_lineno, col_offset, end_col_offset)`.
- Then match the location to the enclosing `ast.If`, `ast.While`, `ast.For`, `ast.IfExp`, `ast.Match`/`match_case`, `ast.BoolOp` (short-circuit), `ast.Try`/`except`, or a comprehension `if`, by span containment. Build the table lazily on the first `PY_START` of each code object and cache it keyed by the code object.
- Treat `co_branches()` as possibly private or undocumented. Feature-detect it with `hasattr(code, "co_branches")` and fall back to the `dis` scan.
- Loops: `JUMP` fires on backward jumps (each iteration), and the loop-exit decision arrives as a branch event at `FOR_ITER` or the `while` test. Record **iteration counts per loop** plus the first N iterations rather than every event, to bound trace size.
- Exceptions:
  - `PY_UNWIND` means a frame exited via an exception. It pairs with `PY_START` the way `PY_RETURN` does.
  - `RAISE` gives the raise site, and `EXCEPTION_HANDLED` tells you which `except` caught it.
  - `PY_UNWIND` and `RAISE` are global-only and cannot be disabled, so filter them cheaply in the callback.
- Async: coroutines emit `PY_YIELD`/`PY_RESUME` at each `await`. The recorder's call stack must be per logical task (stored in the request-scoped object, keyed by task), not per thread.
- **Arguments:** callbacks receive no frame object. To capture argument values at `PY_START`, call `sys._getframe(1)` inside the callback (the monitored frame is the caller) and read `f_locals` for `code.co_varnames[:code.co_argcount + code.co_kwonlyargcount (+ varargs flags)]`. This materializes a frame object and costs extra, so do it only for sampled requests.
  - From 3.13, `frame.f_locals` is a write-through proxy (PEP 667, not re-verified). Reading is fine; never write to it.
- `PY_RETURN` delivers `retval` directly, so no frame access is needed for return values.

---

## 2. Measured overhead: `sys.monitoring` vs `sys.settrace` (coverage.py, SlipCover, PEP numbers)

### Takeaway
Hard, apples-to-apples published numbers are scarce. Some figures are solid:
- Bytecode or `sys.monitoring`-based coverage (SlipCover) has a median overhead of about 5%, versus about 180% for settrace-based coverage.py (ISSTA 2023).
- coverage.py's 3.14 sysmon branch mode was about 2.4x faster than the settrace-based core on one small library.
- The PEP itself says `LINE`-heavy monitoring is only modestly better than `settrace`.

The big wins come from returning `DISABLE` after the first hit. A per-request recorder **cannot** use that trick for user-code branches, so expect overhead closer to "every event fires" for traced requests.

### Cited Findings
- PEP 669 design claims:
  - With no active events, the PEP expects "a small positive impact on performance", citing "Experiments show between 1 and 2% speedup from not supporting" `sys.settrace()` directly.
  - With a few events, callback overhead "will be orders of magnitudes less than for `sys.settrace()`".
  - For `LINE`-instrumented code, "performance should be better than `sys.settrace`, but not by that much".

  — [PEP 669](https://peps.python.org/pep-0669/)
- During PEP review, a commenter noted the PEP lacked time benchmarks for common usages such as coverage, profiling and tracing. — [discuss.python.org PEP 669 thread (via search)](https://discuss.python.org/t/pep-669-low-impact-monitoring-for-cpython/13018.md)
- Coverage.py 7.4.0 (2023-12-27) introduced `COVERAGE_CORE=sysmon` and said it "should be faster for line coverage, but not for branch coverage" (on 3.12). — [changelog](https://coverage.readthedocs.io/en/latest/changes.html)
- Coverage.py 7.9.1 (2025-06-13): "On Python 3.14+, the 'sysmon' core is now the default if it's supported for your configuration. Plugins and dynamic contexts are still not supported with it." — [changelog](https://coverage.readthedocs.io/en/latest/changes.html). A search summary attributed this to 7.9.2; the changelog, the primary source, says 7.9.1.
- Coverage.py 7.11.1 (2025-11-07): sysmon "cannot be used with some concurrency settings, with dynamic context, and in Python 3.12/3.13, with branch measurement". 7.15.3 (2026-08-02) reiterates that "the sysmon core is incompatible with dynamic contexts". — [changelog](https://coverage.readthedocs.io/en/latest/changes.html)
  - Relevance: dynamic contexts are coverage.py's per-test attribution. Even coverage.py has **not** solved "attribute execution to a context" on the sysmon core, because `DISABLE` makes later contexts invisible.
- Coverage.py 7.17.3 (2026-11-11): on 3.13+, "using the C tracer should result in test suites running about 8% to 12% faster". This refers to the settrace C tracer, not sysmon. — [changelog](https://coverage.readthedocs.io/en/latest/changes.html)
- Ned Batchelder on why sysmon is faster: unlike settrace, which calls the recording function for every executed line even after it has been recorded, sys.monitoring lets you "disable an event once it's fired", so repeat executions cost nothing. — [Faster branch coverage measurement (Mar 2025)](https://nedbatchelder.com/blog/202503/faster_branch_coverage_measurement)
- Hugo van Kemenade measured coverage 7.7 (sysmon branch, 3.14a6) at "2.42 ± 0.03 times faster" than 7.6 on a very small pure-Python library with branch coverage on. This is a single small benchmark. — [Mastodon post (via hackers.pub)](https://hackers.pub/@hugovk@mastodon.social/0195a9d7-f222-74f1-969c-a34e2ac32292/quotes)
- SlipCover (Pizzorno & Berger, ISSTA 2023) reports a CPython median overhead of 5%, versus coverage.py's median 180% on CPython and 1,300% on PyPy. It locates branches by AST transformation and inserts low-overhead instrumentation. On 3.12+ it uses `sys.monitoring` instead of bytecode rewriting. — [arXiv 2305.02886](https://arxiv.org/abs/2305.02886); [ISSTA 2023 listing](https://2023.issta.org/details/issta-2023-technical-papers/87/SlipCover-Near-Zero-Overhead-Code-Coverage-for-Python)
- FOSDEM 2024 slides on the 3.12 monitoring API show runtime figures of 3.5x, 1.2x and 2.7x comparing settrace and sys.monitoring. The extracted slide text does not say which figure belongs to which tool or workload, so they are not reliable as stated. — [FOSDEM 2024 slides](https://archive.fosdem.org/2024/events/attachments/fosdem-2024-1678-python-3-12-s-new-monitoring-and-debugging-api/slides/22878/Python3_12MonitoringFOSDEM20min_Ni4FuSI.pdf)

### Inferences
- **Key design consequence:** coverage tools are fast because each location reports once and then returns `DISABLE`. A per-request flow recorder needs *every* branch and call in user code for every sampled request. `DISABLE` and `restart_events()` are global across threads and tools, and `restart_events()` is "slow", so you cannot re-arm per request.
- The realistic overhead model is:
  - (a) Near zero for non-user code: `DISABLE` at `PY_START`.
  - (b) A Python-level callback (roughly sub-microsecond to about 1 µs each, unmeasured here) for **every** call, return and branch in user code, while monitoring is armed.
  - (c) Instrumented bytecode reduces specialization in user code.
- Plan for a measurable slowdown, plausibly tens of percent, on branch-heavy handlers during traced requests. This estimate is unverified; benchmark it.
- Mitigation: keep events disarmed most of the time, and arm them with `set_local_events` only on user code objects while at least one sampled request is in flight (reference count). This trades a "slow" re-instrumentation on arm and disarm for zero steady-state cost. Alternatively, keep events armed permanently and drop unsampled requests with a single `ContextVar.get()` check in the callback.
- A C-extension callback (as coverage.py's CTracer does for settrace) would cut per-event cost substantially. A pure-Python prototype first, with a C or Rust (PyO3) callback later, is a reasonable path. This is an inference; there are no measurements here.

### Gaps
- No primary, apples-to-apples benchmark of "all user-code CALL/RETURN/BRANCH events always firing" under sys.monitoring versus settrace on a web workload was found.
- No numbers were found for the cost of `set_local_events` or `restart_events` on large code bases.

---

## 3. Scoping to user code and to the current request (contextvars, asyncio, threads, background tasks); fallback for Python earlier than 3.12

### Takeaway
Use static filtering for "user code only": decide once per code object at `PY_START` and return `DISABLE` for anything outside the app root, which costs nothing afterwards. Use dynamic filtering for "this request only": a `ContextVar` holding a **mutable** recorder object that the callback checks on every event. asyncio tasks and anyio worker threads (FastAPI sync endpoints) receive a *copy* of the context, so the same recorder object is visible there. Plain `threading.Thread` and executors need explicit propagation. Before 3.12, use import-time AST or bytecode rewriting (SlipCover-style) rather than `sys.settrace`.

### Cited Findings
- `sys.monitoring` is interpreter-global, with no per-thread enabling, so per-request filtering must happen inside callbacks. — [PEP 669](https://peps.python.org/pep-0669/)
- anyio's `to_thread.run_sync` (used by Starlette and FastAPI for `def` endpoints and dependencies) runs the callable under a **copy** of the current context. Writes made inside the thread (`var.set(...)`) are not propagated back to the caller.
  - A Starlette PR test asserts that the value set in the sync function is not visible afterwards. — [encode/starlette#1525](https://github.com/encode/starlette/pull/1525)
  - The FastAPI maintainer explains that a ContextVar set in sync dependencies persists only in the worker thread. — [FastAPI issue (Lightrun mirror)](https://lightrun.com/answers/tiangolo-fastapi-feature-ability-to-change-contextvars-in-sync-dependencies)
  - A community post describes the same behavior. — [DEV Community post](https://dev.to/earthbound_misfit/the-context-copy-gets-the-write-the-endpoint-never-sees-it-31dm)
- `asyncio.to_thread`, `trio.to_thread.run_sync` and `anyio.to_thread.run_sync` all copy the current task's context into the worker thread, without back-propagation. — [discuss.python.org: back-propagation of contextvar changes](https://discuss.python.org/t/back-propagation-of-contextvar-changes-from-worker-threads/15928)
- An import-hook (AST-rewriting) approach for branch tracking conflicts with pytest's assertion-rewriting import hook, and it cannot instrument modules imported before the hook is installed (for example under pytest-cov). — [discuss.python.org (nedbat)](https://discuss.python.org/t/updating-sys-monitoring-how-branch-events-are-disabled/59527); [Pushing back on sys.monitoring](https://nedbatchelder.com/blog/202407/pushing_back_on_sysmonitoring)
- Pre-3.12 baselines: SlipCover's bytecode-rewriting approach has about 5% median overhead, versus about 180% for the settrace-based coverage.py. — [arXiv 2305.02886](https://arxiv.org/abs/2305.02886)

### Inferences
- **Recommended skeleton** (3.12+, not run in this session):
  ```python
  import sys, contextvars
  M, E = sys.monitoring, sys.monitoring.events
  TOOL = next(i for i in range(6) if M.get_tool(i) is None)   # don't assume COVERAGE_ID
  M.use_tool_id(TOOL, "flow-recorder")
  REC = contextvars.ContextVar("flow_rec", default=None)      # holds a *mutable* recorder
  BR = (E.BRANCH_LEFT | E.BRANCH_RIGHT) if hasattr(E, "BRANCH_LEFT") else E.BRANCH
  LOCAL = E.PY_RETURN | E.PY_YIELD | E.PY_RESUME | BR | E.JUMP
  _seen = {}
  def on_start(code, off):
      u = _seen.get(code)
      if u is None:
          u = _seen[code] = code.co_filename.startswith(APP_ROOT)   # + exclude site-packages
          if u: M.set_local_events(TOOL, code, LOCAL)
      if not u:
          return M.DISABLE              # static decision: valid for all requests forever
      r = REC.get()
      if r is not None and not r.full:  # dynamic per-request filter
          r.enter(code, sys._getframe(1))
  def on_branch(code, src, dst):
      r = REC.get()
      if r is not None: r.branch(code, src, dst)   # never DISABLE: the next request needs it
  M.register_callback(TOOL, E.PY_START, on_start)
  for ev in (E.BRANCH_LEFT, E.BRANCH_RIGHT) if BR != E.BRANCH else (E.BRANCH,):
      M.register_callback(TOOL, ev, on_branch)
  # ... PY_RETURN/PY_UNWIND/RAISE/EXCEPTION_HANDLED/JUMP callbacks similarly
  M.set_events(TOOL, E.PY_START | E.PY_UNWIND | E.RAISE | E.EXCEPTION_HANDLED)
  ```
  Calling `set_local_events` from inside a `PY_START` callback mirrors what coverage.py's sysmon core is believed to do. That belief was not verified in this session.
- **Middleware pattern:** in ASGI middleware, decide sampling, create `Recorder()`, `token = REC.set(rec)`, `await app(...)`, then `REC.reset(token)` and hand `rec` to the async exporter.
  - Because only the *reference* is copied into anyio threads and new tasks, appends from a sync endpoint or `asyncio.gather` subtasks land in the same recorder.
  - The recorder must be safe for concurrent appends: use a per-thread or per-task sub-buffer merged at the end, which matters especially on free-threaded builds.
  - Never call `REC.set()` inside callbacks.
- **Context propagation gaps** (no automatic copy):
  - `threading.Thread(...)`, `ThreadPoolExecutor.submit` (wrap with `contextvars.copy_context().run`), Celery/RQ jobs (pass a trace ID explicitly), and `loop.run_in_executor` (believed not to copy context; verify).
  - Starlette/FastAPI `BackgroundTasks` run after the response in the request's context. Decide whether to attribute them to the request (recommended: a child segment flagged "post-response") or to stop recording at response end.
  - Python 3.14 reportedly added a `-X thread_inherit_context` / `sys.flags.thread_inherit_context` option, on by default in free-threaded builds, which makes new threads inherit the caller's context. This was not verified in this session; check the What's New in 3.14 docs.
- **Concurrency correctness:** concurrent requests interleave on one event loop. Because each asyncio Task runs in its own context and callbacks execute synchronously in the running task's context, `REC.get()` inside the callback returns the correct request.
  - This assumes callbacks run in the context of the executing code, which is the expected behavior but was not explicitly documented in sources fetched here.
- **User-code filter:**
  - Resolve against real paths (`os.path.realpath(code.co_filename)`).
  - Exclude `sysconfig.get_paths()["stdlib"]`, `"purelib"` and `"platlib"`, plus `<frozen ...>` and `<string>`.
  - Allow-list the project root, plus optional opt-in packages.
  - Cache by code object; code objects are hashable and stable.
- **Fallback before 3.12:**
  - (a) `sys.setprofile` for call/return/c_call/exception only, which has lower cost than settrace but gives no lines or branches.
  - (b) `sys.settrace` with `frame.f_trace_lines=False` for frames outside user code. Infer branches from consecutive line "arcs", as coverage.py historically did.
  - (c) The preferred option for production is an import hook (`importlib.abc.MetaPathFinder` + `SourceLoader.source_to_code`) that rewrites the AST of user modules to call `rec.branch(id)` at the start of each `if`/`else`/loop body. This is SlipCover's idea; pytest's assertion rewriting is the reference implementation of the hook mechanics.
  - Downsides: modules imported before the hook are missed, there is friction with other import hooks, and it changes `.pyc` caching.

### Gaps
- No primary source was found confirming the 3.14 `thread_inherit_context` default or `run_in_executor` context behavior.
- No published overhead numbers were found for a ContextVar check inside a monitoring callback.

---

## 4. Capturing values safely (repr, ORM lazy loads, large payloads, sampling) and free-threaded Python 3.13t/3.14t

### Takeaway
Never call arbitrary `__repr__`/`__str__` or attribute getters on application objects in the hot path. Serialize with a type-dispatched, depth- and size-bounded walker that reads already-loaded state only (for SQLAlchemy, the instance `__dict__`). Copy production limits from Datadog, roughly 1 snapshot per second per probe with bounded depth and size. On free-threaded builds, monitoring has had real data races; coverage.py fixed one in 2025, and the recorder's buffers must be thread-safe.

### Cited Findings
- Datadog Dynamic Instrumentation, from the dd-trace-rb docs as seen via a mirror:
  - Default limits are 5,000 invocations per second for non-capturing probes and **1 invocation per second for capturing (snapshot) probes**, both overridable per probe.
  - A **circuit breaker** auto-disables a probe whose execution overhead exceeds **0.5 s of CPU time**; the threshold is configurable globally.
  - A disabled probe must be recreated in the UI.

  These numbers come from Ruby-tracer documentation via a mirror and were not confirmed on Datadog's main site. — [dd-trace-rb docs (Algolia mirror)](https://docsearch.algolia.com/mcp/docs/repo/datadog/dd-trace-rb)
- Datadog's official page says "Metric instrumentations are not rate limited and execute every time the method or line is invoked". Redaction is handled via a separate "Sensitive data scrubbing" feature. — [Datadog Dynamic Instrumentation docs](https://docs.datadoghq.com/tracing/trace_collection/dynamic_instrumentation/)
- Free-threading:
  - Coverage.py 7.8.1 (2025-05-21) "Fixed a race condition when using sys.monitoring with free-threading Python".
  - Coverage.py 7.14.2 (2026-06-20) stopped distributing wheels for 3.13 free-threaded builds.

  — [changelog](https://coverage.readthedocs.io/en/latest/changes.html)
- CPython issue gh-131141 reports a ThreadSanitizer data race on 3.13.2 free-threaded builds when registering a `sys.monitoring` CALL callback across many threads. The root cause was not confirmed from the snippet. CPython's free-threading test suite includes `test_monitoring.py`, which toggles instrumentation across threads. — [gh-131141 (mirror)](https://scriptagc.wasmer.app/https_github_com/python/cpython/issues/131141); [Debian source of test_monitoring.py](https://sources.debian.org/src/python3.13/3.13.11-1/Lib/test/test_free_threading/test_monitoring.py)
- The free-threading HOWTO is titled "Python experimental support for free threading" for 3.13 and "Python support for free threading" in the current (3.14+) docs, reflecting the change in status. — [3.13 HOWTO](https://docs.python.org/3.13/howto/free-threading-python.html); [current HOWTO](https://docs.python.org/3/howto/free-threading-python.html)

### Inferences
- **Safe value capture rules** (engineering judgment):
  1. Dispatch on exact type:
     - Primitives (`int`, `float`, `bool`, `None`, short `str`/`bytes`): copy, truncating strings to about 256 characters and bytes to about 64.
     - `list`/`tuple`/`dict`/`set`: capture the first N items (for example 20), up to depth 3, and record `len()`.
     - `dataclass`/`pydantic` models: read fields via `__dict__` / `model_fields`, not getters.
     - Anything else: `{"type": qualname, "id": id(obj)}` with **no** `repr()`.
  2. For SQLAlchemy ORM instances, read `obj.__dict__` and skip `_sa_instance_state`. Use `sqlalchemy.inspect(obj).unloaded` to list lazy attributes without triggering SQL. `getattr` on an unloaded relationship issues a query, and inside an async session it raises `MissingGreenlet`.
  3. Same idea for Django model instances (`__dict__`, not related managers), file and stream objects (never read), and generators or iterators (never consume).
  4. Use `reprlib.Repr` (stdlib, with `maxlevel`/`maxstring`/`maxlist`) only for known-safe builtins.
  5. Apply redaction by key name (`password`, `token`, `authorization`, `secret`, `cookie`, `card`) before buffering.
- **Defer serialization:** in the callback, store references (or, for mutable containers, shallow-copied bounded slices). Serialize off the hot path only for requests that are kept under tail sampling. Holding references extends object lifetimes, so cap it.
- Capturing values is the most expensive part of recording. Make it a separate, lower sampling tier: flow-only for X% of requests, flow plus values for Y% (much smaller), and always values for errored requests if tail-decided. That last tier is only possible if values were captured as references.
- Free-threaded builds (3.13t/3.14t): callbacks run truly in parallel.
  - Keep recorder state per thread (`threading.local`) or per task, merged on request end.
  - Make the code-object cache tolerate benign races (dict get/set is internally locked in free-threaded CPython; a duplicate first-time `set_local_events` is harmless).
  - Avoid global counters without atomics.

### Gaps
- Datadog's per-language capture limits (max depth, collection size, string length, field count) were not retrievable from the official pages fetched. The Python `ddtrace` implementation details (bytecode injection versus `sys.monitoring`) were not confirmed.
- No source was found describing how Sentry bounds overhead for any equivalent per-request local-variable capture.

---

## 5. Java: java agents (ByteBuddy/ASM), JaCoCo probes, JFR, OpenTelemetry agent, JDI, and Spring Boot

### Takeaway
Java has no built-in per-request branch event API. The production-grade approach is a `-javaagent` that uses ByteBuddy `Advice` for method entry, exit, arguments, return values and exceptions on user packages. For branches, add ASM-inserted probes at JaCoCo-style "strategic" control-flow points. Unlike JaCoCo's global per-class `boolean[]`, those probes must write into a per-request recorder found via `ThreadLocal` or a scoped value plus explicit propagation. JFR's new method tracing (JDK 25, JEP 520) is method-level only and is not bounded to JFR's usual <1% overhead.

### Cited Findings
- JaCoCo keeps one `boolean[]` per instrumented class, with one entry per probe. The `.exec` format stores a boolean array per class ID with no line or method info until analysis. "To keep the runtime overhead minimal, only a few probes are inserted at 'strategic' places", using control-flow analysis. — [JaCoCo implementation design](https://www.jacoco.org/jacoco/trunk/doc/implementation.html); [JaCoCo control flow analysis](https://www.jacoco.org/jacoco/trunk/doc/flow.html)
- A JaCoCo maintainer reported that adding probes at every INVOKE opcode (about 2.4x as many probes) gave runtimes of 100–146% of the then-current release. This is evidence of how probe density drives cost. — [JaCoCo mailing list / Google Groups (via search)](https://groups.google.com/g/jacoco/c/MztSENoOh2I/m/Chok-XdGAwAJ)
- The JaCoCo agent exposes JMX operations to dump and reset execution data at any time, the usual way to get per-test snapshots. No published overhead numbers for that pattern were found. — [JaCoCo docs (via search)](https://www.jacoco.org/jacoco/trunk/doc/implementation.html)
- **JEP 520, "JFR Method Timing & Tracing"**, was delivered in **JDK 25**.
  - It adds `jdk.MethodTiming` and `jdk.MethodTrace` events with a filter, for example `jdk.MethodTrace#filter=java.util.HashMap::resize`, annotation targets such as `@jakarta.ws.rs.GET`, and `::<clinit>`.
  - It adds the option aliases `method-trace` and `method-timing`.
  - Non-goal: "It is not a goal to remain within this constraint [<1% CPU] when timing and tracing methods."

  — [JEP 520](https://openjdk.org/jeps/520)
- OpenTelemetry Java agent: the performance page says the agent "has minimal impact" but publishes no numbers. It recommends sampling, disabling instrumentations (`-Dotel.instrumentation.<name>.enabled=false`), more heap, and keeping manual instrumentation minimal, because `@WithSpan` on every method produces high span volume. — [OpenTelemetry Java agent performance](https://opentelemetry.io/docs/zero-code/java/agent/performance/)
- Datadog Dynamic Instrumentation supports Java with JDK 8+ and does not support Kotlin coroutines. It needs Agent 7.49.0+ and Remote Configuration, and is not compatible with Azure App Services or serverless. — [Datadog DI docs](https://docs.datadoghq.com/dynamic_instrumentation/)

### Inferences
- **Recommended Java design** (standard ByteBuddy/ASM APIs, not re-verified this session):
  ```java
  new AgentBuilder.Default()
    .type(nameStartsWith("com.acme."))                       // user packages only
    .transform((b, td, cl, m, pd) -> b.visit(Advice.to(FlowAdvice.class)
        .on(isMethod().and(not(isAbstract())))))
    .installOn(inst);
  class FlowAdvice {
    @Advice.OnMethodEnter static long enter(@Advice.Origin("#t.#m") String m,
                                            @Advice.AllArguments Object[] args) {
      Recorder r = Recorder.CURRENT.get(); return r == null ? 0 : r.enter(m, args); }
    @Advice.OnMethodExit(onThrowable = Throwable.class) static void exit(@Advice.Enter long id,
        @Advice.Return(typing = Assigner.Typing.DYNAMIC) Object ret, @Advice.Thrown Throwable t) {
      Recorder r = Recorder.CURRENT.get(); if (r != null) r.exit(id, ret, t); }
  }
  ```
  - `Advice` inlines the code into the method, so it avoids an extra call frame and is JIT-friendly. Keep the "not recording" fast path to one `ThreadLocal.get()` plus a null check.
  - `@Advice.AllArguments` allocates an `Object[]` on every call. Gate it behind the null check, or use the argument-by-index form only when recording.
- **Branches in Java:**
  - Use an ASM `MethodVisitor` (or ByteBuddy `AsmVisitorWrapper`) to insert `Recorder.br(classId, probeId)` before each jump target and after each conditional jump (the fall-through). This is JaCoCo's probe placement.
  - Map probe IDs to line numbers via the `LineNumberTable`. Bytecode has no column info, so the mapping is line-level, plus source-parsing (JavaParser) to tie a line to its `if`/`switch`/loop.
  - JaCoCo itself cannot give per-request data because its probe arrays are global per class and shared across threads. Only "dump-reset per request" with requests serialized would work, which is not viable in production.
- **Context:**
  - Servlet stacks (Spring MVC): a `ThreadLocal` set in a servlet `Filter`/`HandlerInterceptor`.
  - Async hops (`@Async`, `CompletableFuture`, executors): wrap `Runnable`/`Callable`, which is what the OTel agent's executor instrumentation does.
  - WebFlux/Reactor: Reactor `Context` plus `Hooks`/context-propagation, since a request hops threads.
  - Virtual threads (JDK 21+) work with `ThreadLocal`. `ScopedValue` is believed to be final in JDK 25 (JEP 506) and is an immutable-binding alternative; verify.
- **Spring Boot specifics:**
  - Discover endpoints via `RequestMappingHandlerMapping.getHandlerMethods()` (maps `RequestMappingInfo` to `HandlerMethod` for `@RestController` methods).
  - All MVC requests pass through `DispatcherServlet.doDispatch`, a natural place to start and stop recording. You can also instrument it with Advice so no app code changes are needed.
  - Restrict transformation to the app's base package (from `@SpringBootApplication`), to avoid instrumenting Spring/CGLIB proxies (`$$SpringCGLIB$$`) and Hibernate proxies.
- **JDI/JVMTI:** JDI method entry/exit events go through JDWP. Debugger-style per-event round trips are far too slow for production; this is widely known but not measured here. JVMTI `MethodEntry`/`MethodExit` capabilities historically force interpreted or deoptimized execution (unverified). Prefer bytecode instrumentation.
- Retransformation (`Instrumentation.retransformClasses`) allows enabling and disabling instrumentation per class at runtime. This is the Java equivalent of arming and disarming, and it is how Datadog and Lightrun-style tools add probes live.

### Gaps
- No primary benchmark was found for ByteBuddy Advice per-method overhead or for the OTel Java agent (the OTel page publishes none).
- JEP 520 overhead numbers were not found.
- JEP 506 (ScopedValue final in JDK 25) status was not verified in this session.

---

## 6. Node.js: AsyncLocalStorage, diagnostics_channel, V8 precise/block coverage, source maps, Babel/SWC instrumentation

### Takeaway
Use `AsyncLocalStorage` for request context. In Node 24+ it is backed by `AsyncContextFrame` and costs about 7% throughput in one benchmark. V8 block coverage (`Profiler.startPreciseCoverage({callCount:true, detailed:true})`) gives branch-level counts, but they are **isolate-global**, cannot be attributed to concurrent requests, and disable the optimizing compiler for accurate counts. That makes it good for dev, CI and "which branches does this endpoint touch" sampling on an isolated worker, and wrong for production per-request recording. For production per-request branches, use build-time source instrumentation (Babel/SWC, istanbul-style) that writes into the ALS-scoped recorder, then map back through source maps.

### Cited Findings
- V8 coverage modes:
  - **Best-effort coverage** "does not introduce any runtime overhead", but may lose data to GC.
  - **Precise coverage** keeps feedback vectors alive, increasing memory.
  - Function granularity shipped in V8 5.9 and block granularity in V8 6.2.
  - Block coverage inserts an `IncBlockCounter` bytecode at strategic points: before the `then` body, before the `else` body, and after the whole statement for non-local control flow. The source ranges come from the parser.

  — [V8 blog: JavaScript code coverage](https://v8.dev/blog/javascript-code-coverage)
- Inspector API: `Profiler.startPreciseCoverage(callCount, detailed)` takes `callCount` (counts versus binary) and `detailed` (block versus function). `Profiler.takePreciseCoverage()` returns source ranges with counts as a delta since the last call, and `Profiler.stopPreciseCoverage()` frees data. Because optimized functions stop incrementing counters, "the optimizing compiler must be disabled for their reported execution count to remain accurate." — [V8 blog](https://v8.dev/blog/javascript-code-coverage)
- Node.js v24.0.0: "AsyncLocalStorage now uses AsyncContextFrame by default, which provides a more efficient implementation of asynchronous context tracking." — [Node.js v24.0.0 release notes](https://nodejs.org/blog/release/v24.0.0)
- Platformatic benchmark (i7-7700, 100 connections, pipelining 10, 10 s):
  - Node v24.4.1:
    - Baseline: 57,301 req/s
    - ALS: 53,450 req/s (93.3%)
    - Fastify + full OTel auto-instrumentation: 10,640 req/s (18.6%, P99 104 ms)
    - Fastify + selective OTel: 20,568 req/s (35.9%)
  - Node v22.17.1:
    - ALS: 90.2% of baseline
  - The gains were attributed to PRs #48528 (sponsored by Datadog) and #55552.
  - This is a vendor-run single benchmark.

  — [Platformatic, "The hidden cost of context"](https://blog.platformatic.dev/the-hidden-cost-of-context)

### Inferences
- **Recommended Node design:**
  ```js
  const { AsyncLocalStorage } = require('node:async_hooks');
  const als = new AsyncLocalStorage();
  app.use((req, res, next) => sample(req) ? als.run(new Recorder(req), next) : next());
  // build-time plugin rewrites:  if (c) {A} else {B}
  //   => if (c) { __rec(17); A } else { __rec(18); B }
  // with: function __rec(id){ const r = als.getStore(); if (r) r.branch(id); }
  ```
  - Function entry, exit and exception: the same plugin wraps function bodies in `try { __enter(fid, arguments) ... } catch (e) { __throw(fid, e); throw e } finally { __exit(fid) }`. Returns are captured by rewriting `return x` into `return __ret(fid, x)`.
  - Branch IDs map to original TS positions through source maps emitted by the build (`--enable-source-maps` at runtime and `module.findSourceMap()` for lookups; standard Node APIs, not verified here).
  - This is istanbul's instrumentation model with counters replaced by an ALS lookup.
- **Where V8 block coverage still fits:**
  - Coverage is per isolate, so a per-request view is only valid if exactly one request runs in that isolate at a time. Options are a dedicated "probe" worker thread or process that receives mirrored or sampled requests, or tests.
  - Use an in-process `inspector.Session`: `post('Profiler.enable')`, `post('Profiler.startPreciseCoverage', {callCount: true, detailed: true})`, run one request, then `post('Profiler.takePreciseCoverage')`. Expect deoptimized code while it runs.
  - Precise coverage gives counts per block range, not ordering. You learn *which* branches ran and how often, not the sequence.
- `diagnostics_channel`: Node core and many libraries (undici, http, and some DB drivers via tracing channels) publish start, end and error events. Subscribe to them for request boundaries and outbound I/O spans (HTTP/DB calls inside a request) at low cost, instead of monkey-patching. This was not verified in this session; check the Node docs for the exact channel names in the target Node version.
- Monkey-patching (shimmer/require-in-the-middle/import-in-the-middle, as OTel does) gives function-level data for library boundaries but not branches. The Platformatic numbers suggest broad auto-instrumentation is very costly (about 80% throughput loss), so restrict it to user modules plus selected I/O boundaries.

### Gaps
- No primary overhead figure was found for V8 block coverage (precise, detailed mode) on a server workload.
- No overhead numbers were found for istanbul-instrumented production code.
- `diagnostics_channel` channel names and TracingChannel API stability were not verified in this session.

---

## 7. eBPF/uprobes (Pixie, Parca): viable for function/branch level in interpreted or JIT languages?

### Takeaway
No, not for this goal. eBPF uprobes trap (`int3`) at native addresses. Python, Node and Java business logic runs in an interpreter or JIT with no stable native symbols per user function, let alone per branch. Production eBPF tools such as Pixie's dynamic logging are Go-only (compiled, with DWARF). eBPF remains useful for protocol-level request boundaries (HTTP/gRPC/SQL), not for in-process flow.

### Cited Findings
- Pixie's dynamic logging is an alpha feature that "currently only supports logging of Go binaries". It requires debug info, so it breaks with `-ldflags '-w -s'`. Pixie offers profiling for Go, C/C++ and Rust and plans deeper support for Java, Ruby and Python. — [Pixie docs: dynamic Go logging](https://docs.px.dev/tutorials/custom-data/dynamic-go-logging/); [Pixie roadmap](https://docs.px.dev/about-pixie/roadmap/)
- Pixie describes uprobes as inserting a debug trap instruction (`int3` on x86) that triggers a soft interrupt. — [CNCF/Pixie blog: tracing Go function arguments in prod](https://www.cncf.io/blog/2021/11/17/debugging-with-ebpf-part-1-tracing-go-function-arguments-in-prod/)
- Python 3.12 perf support: `PYTHONPERFSUPPORT`, `-X perf` or `sys.activate_stack_trampoline()` makes the interpreter call a small per-function native trampoline, so `perf` can symbolize Python frames. It is a profiling (stack-sampling) aid. A core-dev thread is titled "The performance of Python with perf support is not great". — [Python perf profiling HOWTO](https://docs.python.org/3/howto/perf_profiling.html); [discuss.python.org thread](https://discuss.python.org/t/the-performance-of-python-with-perf-support-is-not-great-and-is-going-to-get-a-lot-worse/25280)
- Kernel-side FOSDEM 2026 slides rank probe types by cost and note that overhead depends on whether the traced function is on a hot path. — [FOSDEM 2026 eBPF hooks gotchas](https://fosdem.org/2026/events/attachments/8GVBN7-ebpf-hooks-gotchas/slides/266651/fosdem_2_smerx2d.pdf)

### Inferences
- In theory CPython's USDT probes (`function__entry`/`function__return`, available only in `--with-dtrace` builds) could feed eBPF function-level events. They are absent from most distro and official builds, give no branch info, and each probe hit is a kernel trap. Arguments would need interpreter-struct walking, which is version-fragile. For JVM and V8, JIT-compiled code moves, so uprobes on user methods are impractical.
- Parca and other continuous profilers are sampling-based. They give statistical hot paths, not per-request flows.

### Gaps
- No published benchmark was found comparing USDT or uprobe-based Python function tracing overhead with `sys.monitoring`.

---

## 8. Production-safety patterns (sampling, per-endpoint switches, ring buffers, async export, caps, circuit breakers) and how Datadog DI, Lightrun and OTel bound overhead

### Takeaway
Commercial live-instrumentation tools bound cost with:
- **Per-probe rate limits.** Datadog uses 1 snapshot per second and 5,000 non-capturing hits per second per probe.
- **CPU-budget circuit breakers.** Datadog's is 0.5 s of CPU per probe.
- **Quotas and sandboxes.** Lightrun's are marketing-level claims only.
- **Sampling and selective instrumentation.** These are OTel's main levers.

A per-request flow recorder should combine:
- head sampling plus per-endpoint switches, for whether to record at all;
- hard per-trace caps;
- lock-free bounded buffers with async batched export;
- a self-measuring breaker that disarms monitoring globally.

### Cited Findings
- Datadog DI (dd-trace-rb docs, via mirror):
  - 5,000 invocations per second for non-capturing probes and 1 per second for capturing probes, overridable per probe.
  - A probe exceeding 0.5 s of CPU time is auto-disabled, and the threshold is configurable globally.

  — [dd-trace-rb docs mirror](https://docsearch.algolia.com/mcp/docs/repo/datadog/dd-trace-rb)
- Datadog metric probes are not rate limited. Dynamic spans and metrics stay active until disabled, and log/snapshot capture expires with the Live Debugger session. — [Datadog DI docs](https://docs.datadoghq.com/tracing/trace_collection/dynamic_instrumentation/)
- Lightrun (vendor claims): quotas impose usage limits for overhead control. A proprietary sandbox prevents state modification. The product offers "capped, throttled performance overhead" with a "dead man" switch, plus RBAC and audit logs. No thresholds are published. — [Lightrun datasheet](https://go.lightrun.com/hubfs/Docs/Lightrun_Datasheet.pdf); [Lightrun architecture](https://lightrun.com/platform/architecture/)
- OpenTelemetry Java: use trace sampling and disable unneeded instrumentations, and avoid `@WithSpan` on every method. — [OTel Java agent performance](https://opentelemetry.io/docs/zero-code/java/agent/performance/)
- In Node, full OTel auto-instrumentation cut Fastify throughput to 18.6% of baseline, versus 35.9% for selective. The author recommends selective instrumentation plus sampling. — [Platformatic](https://blog.platformatic.dev/the-hidden-cost-of-context)
- In Python, `sys.monitoring` `set_events` and `restart_events` "should be regarded as slow". Arming and disarming is therefore an infrequent control-plane operation, not a per-request one. — [PEP 669](https://peps.python.org/pep-0669/)

### Inferences
- **Recommended control plane** (engineering judgment):
  1. **Per-endpoint enable switch plus head sampling.** Use a route-to-rate map (default 0 in production, for example 1% for chosen endpoints, 100% for a debug header or an allow-listed user), evaluated in middleware *before* creating the recorder. Unsampled requests then pay only the ContextVar/ThreadLocal/ALS null check, or nothing if monitoring is disarmed.
  2. **Arm and disarm instead of always-on.**
     - Python: `set_events`/`set_local_events` on user code only when sampled traffic exists.
     - Java: retransform classes when a route is enabled.
     - Node: ship instrumented builds behind a flag, or load an instrumented variant per route.
  3. **Hard caps per trace:** max events (for example 10k), max depth, max loop iterations recorded per loop (first N plus a count), and max captured bytes. When a cap is hit, set `rec.full=True`. Callbacks then return immediately, and the trace is marked truncated.
  4. **Tail sampling of *export*, not recording.** Keep every sampled trace in a bounded per-worker ring buffer, but export only errors, slow requests (above p95) and a small random fraction. Recording cost is paid for every sampled request, so head sampling is what controls overhead.
  5. **Async export:** a background thread or task drains the ring buffer and serializes values (deferred serialization from section 4), with batching, compression, a bounded queue, and drop-oldest on overflow. Never block the request on export.
  6. **Circuit breaker:**
     - Track request latency, or CPU time per sampled request, with recording on versus a rolling baseline for unsampled requests on the same route.
     - If the overhead ratio exceeds a threshold (for example a 10% p50 increase), or total recorder CPU exceeds X ms/s (Datadog-style budget), disarm globally (`set_events(TOOL, 0)`, clear local events) and back off exponentially before re-arming.
     - Optionally sample callback cost with `perf_counter_ns` on 1/N events.
  7. **Safety:**
     - Wrap every callback body in `try/except BaseException`, then disable the tool on repeated errors; an exception in a monitoring callback propagates into user code (PEP/docs semantics not fetched here, so verify).
     - Redact before buffering.
     - Never call user `__repr__`.
     - Keep a kill switch via remote config, Datadog/Lightrun style.

### Gaps
- No primary Datadog documentation was retrieved stating the Python- or Java-specific DI rate limits and capture limits; only the Ruby mirror.
- Sentry's approach (local-variable capture in stack frames, profiling sample rates) was not researched in this session.
- Lightrun's thresholds are unpublished; only marketing claims were found.
- The behavior when a `sys.monitoring` callback raises (whether the exception propagates into user code, or the event or tool is disabled) was not confirmed from a primary source in this session.
- Python 3.15 status (scheduled for October 2026 per the release schedule, not verified) and any 3.15 `sys.monitoring` changes were not researched. Check What's New in Python 3.15 before finalizing.
