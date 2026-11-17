# Static analysis for EasyAPI: endpoints, functions, control flow, and graph IR (as of 12 Nov 2026)

Method note: library maintenance and license data comes from live GitHub GraphQL/REST queries and the PyPI JSON API run on 2026-11-12. "Last commit" means the latest commit on the default branch. Where GitHub reports a license as "Other/NOASSERTION", the LICENSE file itself was read. Visitor coverage for the CFG libraries was checked by reading their source with `grep "def visit_"`.

---

## 1. Python CFG and analysis libraries: maintenance, license, and syntax support for 3.12–3.14

### Takeaway
None of the existing Python CFG libraries fits EasyAPI as-is. staticfg, python-graphs, Scalpel and PyCG are unmaintained or archived. None of the graph-producing ones handles `match`, and several also miss `try`, `with` or `async for`. The only one that handles `match` is PyFlowchart, an actively maintained MIT flowchart generator, but it outputs flowchart.js DSL rather than a graph IR. The practical base is the stdlib `ast` module, or LibCST when lossless round-tripping matters, plus beniget/gast for def-use chains and a custom CFG builder. Copyleft is a concern in two places: astroid is LGPL-2.1 and pyan3 is GPL-2.0-or-later.

### Cited Findings
**CFG builders**
- **staticfg**: Apache-2.0, 216 stars. Last commit 2022-08-07; last PyPI release 0.9.5 (2020-06-11). Its builder has visitors for If/While/For/Break/Continue/Return/Raise/Yield/Await/FunctionDef/AsyncFunctionDef, but **none for Try, With, Match, AsyncFor or AsyncWith** (zero occurrences of "Match", "Try" or "With" in builder.py). — [staticfg repo](https://github.com/coetaur0/staticfg); [builder.py](https://github.com/coetaur0/staticfg/blob/HEAD/staticfg/builder.py); [PyPI](https://pypi.org/project/staticfg/)
- **Scalpel** (SMAT-Lab; CFG builder derived from staticfg, plus PyCG-based call graph): Apache-2.0, 335 stars. Last commit 2024-03-28; PyPI `python-scalpel` 1.0b0 (2022-12-25). Its CFG builder adds Try, With, AsyncWith, AsyncFor, Global, Nonlocal and Delete visitors, but has **no Match visitor and no TryStar visitor (`except*`)**. — [Scalpel repo](https://github.com/SMAT-Lab/Scalpel); [cfg/builder.py](https://github.com/SMAT-Lab/Scalpel/blob/HEAD/src/scalpel/cfg/builder.py); [PyPI](https://pypi.org/project/python-scalpel/)
- **python-graphs** (Google Research): Apache-2.0, **archived**. Last commit 2022-09-21; last release v1.2.3 (2021-10-07). `control_flow.py` has visitors for If/While/For/Try/Return/Yield/Continue/Break/Raise/Lambda but none for Match, With or AsyncFor (zero occurrences of `ast.Match`, `ast.With` or `AsyncFor`). — [python-graphs repo](https://github.com/google-research/python-graphs); [control_flow.py](https://github.com/google-research/python-graphs/blob/HEAD/python_graphs/control_flow.py)
- **py2cfg**: hosted on GitLab (classroomcode). PyPI 1.0.5 (2024-12-20) requires Python >=3.12 and describes itself as "From any python3 source code, generate Control Flow Graph (CFG)." The PyPI license field is empty. — [PyPI py2cfg](https://pypi.org/project/py2cfg/); [GitLab](https://gitlab.com/classroomcode/py2cfg)
- **PyFlowchart**: MIT, 419 stars, **active** (v0.6.0 released 2026-03-12). Handles Match (`MatchCaseCondition`), loops including AsyncFor, If, Return, Yield and Break/Continue. It produces flowchart.js DSL or interactive HTML. Its `Flowchart.from_code(code, field="", inner=True, simplify=True, conds_align=False)` can target a single `Class.method`, and `simplify` collapses a one-line if/loop body into a single node. — [PyFlowchart repo](https://github.com/cdfmlr/pyflowchart); [ast_node.py](https://github.com/cdfmlr/pyflowchart/blob/HEAD/pyflowchart/ast_node.py); [README](https://github.com/cdfmlr/pyflowchart/blob/HEAD/README.md)
- **code2flow**: MIT, 4.6k stars, but **unmaintained** (last commit and PyPI 2.5.1 both 2023-01-08). It produces call graphs, not intra-procedural flowcharts. — [code2flow repo](https://github.com/scottrogowski/code2flow); [PyPI](https://pypi.org/project/code2flow/)
- **pyan3**: **GPL-2.0-or-later (copyleft)**, active (v2.9.0, 2026-10-06), requires Python >=3.10,<3.16. A call/use-graph generator. — [pyan repo](https://github.com/Technologicat/pyan); [PyPI pyan3](https://pypi.org/project/pyan3/)

**Parsing, def-use and inference**
- **beniget** (def-use chains over gast): BSD-3-Clause, active (0.5.1, 2026-11-11). **gast** (an AST normalized across Python versions): BSD-3-Clause, 0.7.0 (2025-11-29), last commit 2026-10-27. — [beniget](https://github.com/serge-sans-paille/beniget); [gast](https://github.com/serge-sans-paille/gast); [PyPI beniget](https://pypi.org/project/beniget/)
- **LibCST**: MIT for contributions, but some files derived from CPython are PSF-licensed (modifications dual MIT/PSF). v1.9.0 (2026-07-29). The changelog lists "Add support for Python 3.15", "Recognize Python 3.14 parser configurations", "Support parsing of t-strings" and PEP 701 support. — [LibCST LICENSE](https://github.com/Instagram/LibCST/blob/HEAD/LICENSE); [CHANGELOG](https://github.com/Instagram/LibCST/blob/HEAD/CHANGELOG.md)
- **astroid** (pylint's inference engine): **LGPL-2.1-or-later**, active (v4.3.4, 2026-10-08), requires Python >=3.10. — [astroid repo](https://github.com/pylint-dev/astroid); [PyPI](https://pypi.org/project/astroid/)
- **Jedi**: MIT ("All contributions towards Jedi are MIT licensed"), 0.20.1 (2026-10-12), requires Python >=3.10. — [Jedi LICENSE](https://github.com/davidhalter/jedi/blob/HEAD/LICENSE.txt); [PyPI](https://pypi.org/project/jedi/)

**Type checkers usable as resolvers over LSP**
- **pyright**: MIT, release 1.1.414 (2026-09-09), last commit 2026-11-10. Ships `callHierarchyProvider.ts`. — [pyright LICENSE](https://github.com/microsoft/pyright/blob/HEAD/LICENSE.txt); [callHierarchyProvider.ts](https://github.com/microsoft/pyright/blob/HEAD/packages/pyright-internal/src/languageService/callHierarchyProvider.ts)
- **basedpyright** (pyright fork): v1.40.2 (2026-10-04). — [basedpyright](https://github.com/DetachHead/basedpyright)
- **ty** (Astral): MIT, still 0.0.x (0.0.101, 2026-11-11). Implements LSP `prepareCallHierarchy` and incoming/outgoing calls (`crates/ty_ide/src/call_hierarchy.rs`, `ty_server/.../call_hierarchy_*_calls.rs`). — [ty repo](https://github.com/astral-sh/ty); [ruff/ty_ide call_hierarchy.rs](https://github.com/astral-sh/ruff/blob/HEAD/crates/ty_ide/src/call_hierarchy.rs)
- **pyrefly** (Meta): MIT, 1.4.1 (2026-11-05). Implements call hierarchy (`pyrefly/lib/lsp/non_wasm/call_hierarchy.rs`). — [pyrefly repo](https://github.com/meta/pyrefly); [call_hierarchy.rs](https://github.com/meta/pyrefly/blob/HEAD/pyrefly/lib/lsp/non_wasm/call_hierarchy.rs)
- **pyre-check** (Meta): MIT, **archived**. Last commit 2026-06-26; last release v0.9.23 (2024-10-29). — [pyre-check](https://github.com/meta/pyre-check)

**Call-graph research tools**
- **PyCG**: Apache-2.0, **archived**. Last commit and PyPI 0.0.8 both 2023-11-26. — [PyCG repo](https://github.com/vitsalis/PyCG); [PyPI](https://pypi.org/project/pycg/)
- **JARVIS**: the artifact repo has **no license file** and lists "Python = 3.8" as a prerequisite. It bundles PyCG and Jarvis (`jarvis_cli.py` with `--precision` for flow-sensitivity and `--entry-point`). — [pythonJaRvis repo README](https://github.com/pythonJaRvis/pythonJaRvis.github.io)

**Python syntax that a CFG builder for 3.12–3.14 must handle**
- `match` (3.10, [PEP 634](https://peps.python.org/pep-0634/)), `except*` (3.11, [PEP 654](https://peps.python.org/pep-0654/)), type parameters and `type` aliases (3.12, [PEP 695](https://peps.python.org/pep-0695/)), inlined comprehensions (3.12, [PEP 709](https://peps.python.org/pep-0709/)), t-strings (3.14, [PEP 750](https://peps.python.org/pep-0750/)), unparenthesized `except A, B:` (3.14, [PEP 758](https://peps.python.org/pep-0758/)), and a SyntaxWarning for `return`/`break`/`continue` inside `finally` (3.14, [PEP 765](https://peps.python.org/pep-0765/)).
- The tree-sitter-python grammar has `match_statement`, `type_alias_statement` and `type_parameter` rules. — [tree-sitter-python grammar.js](https://github.com/tree-sitter/tree-sitter-python/blob/HEAD/grammar.js)

### Inferences
- **Recommended Python front end:** use the stdlib `ast` module of the target project's own interpreter. It always parses that interpreter's syntax exactly and carries `lineno/col_offset/end_lineno/end_col_offset`. Add LibCST only if EasyAPI needs comment- and whitespace-preserving edits. Use beniget for def-use chains (local variable to assignment) when resolving receivers such as `repo = Repo(); repo.get()`.
- **Write the CFG builder in-house.** Port ideas from Scalpel's `visit_Try`/`visit_With` and PyFlowchart's node taxonomy, but do not depend on either: Scalpel is unmaintained since 2024 and lacks match/except*, and PyFlowchart's output is a flowchart.js string rather than a graph. A complete visitor set is about 25 statement types, which is a modest effort.
- Treat astroid (LGPL) and pyan3 (GPL) as optional, separately installed plugins, or avoid them. LGPL is usually acceptable as an unmodified dynamic dependency, but GPL-2.0 is not acceptable for an Apache/MIT enterprise distribution.
- Do not adopt PyCG, Scalpel, python-graphs or staticfg as runtime dependencies. They are archived or stale, predate 3.12 syntax, and in the JARVIS case lack a license.

### Gaps
- py2cfg's license and its coverage of match/except* were not checked; the GitLab source was not read.
- I did not find whether tree-sitter-python supports `except*`. A grep for `except_group` in grammar.js returned nothing, but it may use a different rule name.
- basedpyright's LICENSE text was not read directly. GitHub reports it as "Other"; as a pyright fork it is expected to be MIT, but that is unverified.

---

## 2. Designing a human-readable CFG ("n8n-like nodes") vs compiler basic blocks

### Takeaway
There is solid prior art for statement-level, structured graphs that people can read:
- Fraunhofer CPG's **Evaluation Order Graph (EOG)**: vertices are executable AST nodes connected in execution order.
- Joern's **CONTROL_STRUCTURE** typing.
- PyFlowchart's **flowchart node taxonomy**: start, end, operation, condition, input/output, subroutine.

EasyAPI should build a structured, region-based graph: AST-statement nodes nested into collapsible regions for loops, try, with and match. It should derive edges from that graph rather than from basic blocks.

### Cited Findings
- The Fraunhofer CPG EOG is "an intra-procedural directed graph whose vertices are executable AST nodes and edges connect them in the order they would be executed when running the program". It is built as edges between AST nodes after the AST is translated. — [EvaluationOrderGraphPass docs](https://fraunhofer-aisec.github.io/cpg/dokka/main/cpg-core/de.fraunhofer.aisec.cpg.passes/-evaluation-order-graph-pass/index.html); [EOG spec](https://fraunhofer-aisec.github.io/cpg/CPG/specs/eog)
- The CPG platform paper says evaluation order is generally left to right with some exceptions, following the order a compiler would use for expressions. — [A Language-Independent Analysis Platform for Source Code (arXiv 2203.08424)](https://arxiv.org/pdf/2203.08424.pdf)
- Joern's schema represents control constructs as `CONTROL_STRUCTURE` nodes with `CONTROL_STRUCTURE_TYPE` ∈ {BREAK, CONTINUE, DO, WHILE, FOR, GOTO, IF, ELSE, TRY, THROW, SWITCH}. A `CONDITION` edge runs from the control structure to its condition expression, and `CFG` edges link CFG nodes. Every AST node carries CODE, LINE_NUMBER, COLUMN_NUMBER and ORDER. — [Joern CPG schema](https://cpg.joern.io/)
- PyFlowchart maps Python to flowchart.js node types: FunctionDefStart/End, ArgsInput (inputoutput), IfCondition/LoopCondition/MatchCaseCondition (condition), CommonOperation (operation), CallSubroutine and BreakContinueSubroutine (subroutine), YieldOutput/ReturnOutput (inputoutput). It offers `simplify` to collapse one-line bodies and `field` to scope the chart to one function. — [PyFlowchart ast_node.py](https://github.com/cdfmlr/pyflowchart/blob/HEAD/pyflowchart/ast_node.py); [README](https://github.com/cdfmlr/pyflowchart/blob/HEAD/README.md)
- Python 3.14 warns on `return`/`break`/`continue` in `finally` because they silently swallow exceptions. A readable CFG should surface this case. — [PEP 765](https://peps.python.org/pep-0765/)
- Since 3.12, list, dict and set comprehensions are inlined into the enclosing code object (no separate function frame). Generator expressions still create their own code object. — [PEP 709](https://peps.python.org/pep-0709/)

### Inferences (recommended modelling rules)
- **Granularity:**
  - One node per "meaningful statement".
  - Consecutive simple statements (assignments with no calls) fold into one "Code" node, like PyFlowchart's `simplify`.
  - Every statement containing a resolved or unresolved call gets its own "Call" node, or a "Code" node with call chips, so call edges have a precise anchor.
- **Conditionals and loops:**
  - `if/elif/else` becomes one Condition node with labelled `true`/`false` edges; `elif` chains render as a multi-way switch.
  - `match` becomes a Switch node with one edge per `case` pattern (label = pattern source) and an optional implicit "no match" edge.
  - `for/while` becomes a Loop region node. The header carries the iterable or condition. Edges: `loop_body`, `loop_back`, `loop_exit`, and `loop_else` for Python's for/while-else (taken only on normal exit). `break` targets the region exit and `continue` targets the header.
  - `async for` is a Loop region with an `async` flag.
- **Exceptions and context managers:**
  - `try` becomes a Try region with sub-regions body / except[i] / else / finally.
  - Draw `exception` edges from the region boundary to each handler, not from every statement. Per-statement exception edges make basic-block CFGs unreadable; offer them only as a drill-down toggle.
  - `finally` is shown once, with notes that it runs on normal, return and exception paths. Avoid the compiler technique of duplicating `finally` per exit.
  - `except*` is a Try region whose handlers are flagged `group=True`.
  - `with` / `async with` becomes a ContextManager region with an `enter` call, the body, and an `exit` call. The `__exit__` path is an implicit `finally`. For FastAPI, `with Session() as s` deserves a dedicated "resource" badge.
- **Exits:** `return` and `raise` become terminal nodes with edges to the function's synthetic `exit` / `raise-exit` nodes. Early returns show as edges jumping out of nested regions. `raise` inside `try` routes to the matching handler when the type matches statically; otherwise it routes to the function's raise-exit.
- **Generators and async:**
  - `yield` / `yield from` / `await` become Suspend nodes with an edge pair `suspend` → `resume`. In FastAPI, `yield` dependencies split into "setup" (before yield) and "teardown" (after yield, run on response completion).
  - Comprehensions and lambdas stay inside their parent expression node by default. Optionally expand them into a nested sub-graph, since PEP 709 means runtime events for most comprehensions are reported against the parent code object.
- **Decorators:** show them as annotations on the function node. Framework decorators (`@router.get`) become endpoint metadata, and other decorators become "wrapper" nodes on the call edge. Never inline them into the body CFG.
- Keep a hidden basic-block layer (or the EOG) for correctness and runtime mapping, and project it onto the readable region graph. The UI then never has to show basic blocks.

### Gaps
- I found no user study or paper comparing readability of statement-level flowcharts vs basic-block CFGs. The recommendations above are design judgment informed by the cited tools, not empirical findings.
- How Fraunhofer CPG's Python frontend models `match`, `with` and `except*` in its EOG was not verified.

---

## 3. Endpoint discovery: FastAPI, Starlette, Flask, Django/DRF, Litestar (static vs import-time)

### Takeaway
Every target framework keeps a complete, introspectable runtime route registry after import:
- FastAPI and Starlette: `app.routes`, plus a pre-built `Dependant` tree per FastAPI route.
- Flask: `app.url_map` / `view_functions`.
- Django: `get_resolver().url_patterns`; DRF adds `EndpointEnumerator`.
- Litestar: `asgi_router.route_handler_index`.

Import-time discovery is therefore far more accurate than static analysis for prefixes, nested routers, mounted sub-apps and the dependency tree. The cost is executing user code. Recommended approach: import-time first, running in a sandboxed subprocess; a static AST fallback; and source locations recovered via `inspect`/`__code__` so both paths map onto the same static nodes.

### Cited Findings
- **FastAPI:** 0.162.5 (2026-11-11), MIT. — [fastapi repo](https://github.com/fastapi/fastapi)
  - Each route's dependency tree is a `Dependant` dataclass with fields path_params, query_params, header_params, cookie_params, body_params, `dependencies: list[Dependant]` (recursive), name, `call` (the callable), request_param_name, websocket_param_name, response_param_name, background_tasks_param_name, security_scopes_param_name, own_oauth_scopes / parent_oauth_scopes, use_cache, path, and `scope: Literal["function","request"]`. — [fastapi/dependencies/models.py](https://github.com/fastapi/fastapi/blob/HEAD/fastapi/dependencies/models.py)
  - `fastapi/dependencies/utils.py` defines `get_dependant(...)`, `get_parameterless_sub_dependant(...)` (for `dependencies=[Depends(...)]`), `get_typed_signature`, `get_typed_return_annotation`, `_solve_generator` and `solve_dependencies`. `routing.py` calls `get_dependant(path=path, call=call, scope="function")`. — [utils.py](https://github.com/fastapi/fastapi/blob/HEAD/fastapi/dependencies/utils.py); [routing.py](https://github.com/fastapi/fastapi/blob/HEAD/fastapi/routing.py)
  - `yield` dependencies run inside nested `AsyncExitStack`s (request_stack and function_stack). FastAPI warns when "application code is raising an exception and a dependency with yield" swallows it. Background tasks are attached via `solved_result.background_tasks` → `response.background`. — [routing.py](https://github.com/fastapi/fastapi/blob/HEAD/fastapi/routing.py)
  - `include_router(router, prefix=..., dependencies=...)` composes prefixes and router-level dependencies. — [FastAPI docs: Bigger Applications](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
- **Starlette:** 1.10.0 (2026-10-24), BSD-3-Clause. `routing.py` defines `BaseRoute`, `Route`, `WebSocketRoute` and `Mount`; `Mount` exposes a `.routes` property for recursive traversal of sub-apps and routers. — [starlette routing.py](https://github.com/Kludex/starlette/blob/HEAD/starlette/routing.py)
- **Flask:** 3.1.3, BSD-3-Clause. `add_url_rule` adds a `Rule` to `self.url_map` (a werkzeug `Map`) and records `self.view_functions[endpoint] = view_func`, so `app.url_map.iter_rules()` plus `view_functions` gives rule → endpoint → function. — [flask sansio/app.py](https://github.com/pallets/flask/blob/HEAD/src/flask/sansio/app.py)
- **Django:** `django/urls/resolvers.py` defines `get_resolver(urlconf=None)`, `URLPattern` and `URLResolver`, with a `url_patterns` property for recursive traversal of `include()` trees. — [django resolvers.py](https://github.com/django/django/blob/HEAD/django/urls/resolvers.py)
- **DRF:** `rest_framework/schemas/generators.py` has `EndpointEnumerator.get_api_endpoints(patterns, prefix)` and `should_include_endpoint`. Schema generators use these to flatten router-generated viewset routes into (path, method, callback). — [DRF generators.py](https://github.com/encode/django-rest-framework/blob/HEAD/rest_framework/schemas/generators.py)
- **Litestar:** v2.25.0 (2026-10-18), MIT. Routing is compiled into a trie by `self.asgi_router.construct_routing_trie()`; handlers are indexed in `asgi_router.route_handler_index` and exposed via `get_handler_index_by_name`. — [litestar app.py](https://github.com/litestar-org/litestar/blob/HEAD/litestar/app.py)

### Inferences
- **Import-time pros:** exact final paths after `include_router` / `Mount` / `include()` nesting. Exact `Dependant` trees, including class-based and parametrized dependencies and `Annotated[..., Depends()]`. Pydantic request/response models straight from `route.body_field`, `route.response_model` and `route.dependant`. App-level `exception_handlers` and `user_middleware`. Handlers registered by loops or factories that static analysis would miss.
- **Import-time cons:** importing runs arbitrary code (DB connections, env vars, side effects), and fails on missing deps or env. It also cannot see unimported modules.
- **Mitigation:** run discovery in an isolated subprocess or venv with an env-stub mode, a timeout and no network. Then map every callable back to source using `inspect.getsourcefile`, `__code__.co_firstlineno` and `co_qualname` (see section 8) so routes link to static CFG nodes.
- **Static fallback:**
  - Pattern-match decorators (`@app.get`, `@router.post`, `@app.route`, `@api_view`), `APIRouter(prefix=...)`, `app.include_router(x, prefix=...)`, `path()` / `re_path()` / `include()` and DRF `router.register`.
  - Resolve router variables across modules with the import resolver from section 4.
  - Mark unresolved prefixes as `dynamic`.
- **FastAPI-specific nodes to render:**
  - Middleware chain: `app.user_middleware`, outermost first.
  - Dependency tree: from `Dependant.dependencies`. Mark yield dependencies as two nodes (setup/teardown), and mark `use_cache` dedup and `scope` (function vs request).
  - Handler CFG.
  - Exception-handler edges: from `raise HTTPException`/custom exceptions to the matched `app.exception_handlers` entry.
  - BackgroundTasks: `add_task` calls become async "fire-and-forget" edges.
  - Response model / `response_model` serialization node.

### Gaps
- I did not read FastAPI's `include_router` implementation line by line. A grep for `prefix + route.path` found nothing, so the exact prefix/dependency merge code was not confirmed in source; the docs describe the behavior.
- Litestar's controller and router traversal API (`app.routes` vs `route_handler_method_map`) was only partially confirmed.

---

## 4. Inter-procedural call resolution and honest handling of dynamic dispatch

### Takeaway
Static Python call graphs are high-precision but low-recall: PyCG reports 99.2% precision and 69.9% recall. JARVIS claims at least 84% higher precision than PyCG in application-centered, flow-sensitive mode. Both are research artifacts: PyCG is archived, and JARVIS is pinned to Python 3.8 with no license. The pragmatic 2026 stack is tiered:
1. An in-house resolver for imports, `self.` methods and the MRO.
2. A modern type checker over LSP for typed receivers (`self.repo.get` where `repo: UserRepo`). pyright and basedpyright (MIT, mature) both have call hierarchy; ty (MIT, still 0.0.x) and pyrefly (MIT, 1.x) have it too.
3. Runtime-observed edges from `sys.monitoring` CALL events, merged with provenance labels.

### Cited Findings
- **PyCG** (ICSE 2021, pp. 1646–1657):
  - Reported results: precision ≈99.2%, recall ≈69.9%, about 0.38 s per 1,000 LoC.
  - Method: builds an assignment graph over functions, variables, classes and modules via inter-procedural analysis.
  - Evaluation: a micro-benchmark suite plus real-world packages; the benchmark suite is published.
  - Sources: [ICSE 2021 page](https://2021.icse-conferences.org/details/icse-2021-papers/39/PyCG-Practical-Call-Graph-Generation-in-Python); [arXiv 2103.00587](https://arxiv.org/abs/2103.00587); [paper PDF](https://www.spinellis.gr/pubs/conf/2021-ICSE-pycg/html/journal.pdf)
- **JARVIS** (Huang et al., Fudan/Tongji; arXiv 2305.05949, latest v5 Sep 2024):
  - Its critique of PyCG: it is flow-insensitive, does not scale to whole-program analysis when dependent libraries are included, and lacks some language features.
  - Its approach: builds only application-centered call relations, with flow-sensitive intra-procedural type inference interleaved with inter-procedural analysis.
  - Evaluation: 135 micro-benchmark programs and 6 real applications.
  - Reported results: at least 67% faster and 84% higher precision than PyCG; 8.16 s and 227 MB on average. These are the authors' own numbers, not independently replicated.
  - Sources: [arXiv v5](https://arxiv.org/html/2305.05949v5); [arXiv abs](https://arxiv.org/abs/2305.05949v5)
- **LSP call hierarchy:** pyright, ty and pyrefly all implement LSP `prepareCallHierarchy` / incoming / outgoing calls. — [pyright callHierarchyProvider.ts](https://github.com/microsoft/pyright/blob/HEAD/packages/pyright-internal/src/languageService/callHierarchyProvider.ts); [ty call_hierarchy.rs](https://github.com/astral-sh/ruff/blob/HEAD/crates/ty_ide/src/call_hierarchy.rs); [pyrefly call_hierarchy.rs](https://github.com/meta/pyrefly/blob/HEAD/pyrefly/lib/lsp/non_wasm/call_hierarchy.rs)
- **pygls** (Apache-2.0, v2.1.1) is a maintained Python LSP framework, useful if EasyAPI needs to host or drive LSP in Python. — [pygls](https://github.com/openlawlibrary/pygls)
- **`sys.monitoring` CALL events:** the callback `func(code, instruction_offset, callable, arg0)` receives the actual callable object. For instance methods, `callable` is the function from the class and `arg0` is `self`. — [sys.monitoring docs (3.14)](https://docs.python.org/3.14/library/sys.monitoring.html)
- Joern's CPG schema distinguishes `DISPATCH_TYPE` ∈ {STATIC_DISPATCH, DYNAMIC_DISPATCH} on CALL nodes, and has a separate RECEIVER edge from the call to its receiver. — [Joern CPG schema](https://cpg.joern.io/)

### Inferences
- **Resolution pipeline**, run per call site, stopping at the first confident answer:
  1. Lexical/import resolution: own symbol table built from `ast`, with beniget def-use for locals. Covers `from x import f; f()`, module aliases and nested functions.
  2. `self.method()` / `cls.method()` via the class MRO computed from the project's class graph. Emit **all overrides in project subclasses** as candidate edges and flag them `dispatch=dynamic`.
  3. Typed receivers (`self.repo.get` with `self.repo: UserRepo`, or FastAPI `repo: Annotated[UserRepo, Depends(get_repo)]`): ask the type checker for definition (`textDocument/definition`) or outgoing call hierarchy. Prefer basedpyright/pyright for maturity, keep ty/pyrefly as faster options, and record the resolver name in the edge.
  4. Framework knowledge: `Depends(f)` produces a "dependency" edge to `f`, and `BackgroundTasks.add_task(f, ...)` an "async/background" edge to `f`.
  5. Otherwise emit an `unresolved` edge to a synthetic "?" node holding the call expression text, and do not drop it. This is the "honest" part: the UI shows a dashed edge and a count of unresolved calls per function.
- **Edge provenance fields:**
  - `resolution: syntactic | type_inferred | framework | heuristic | observed`
  - `confidence: 0..1`
  - `candidates: [...]` when there is more than one target (dynamic dispatch, union types)
  - `resolver: "ast" | "pyright@1.1.414" | "runtime"`
- **Runtime merge:** a `sys.monitoring` CALL callback gives `callable.__code__` (co_filename, co_firstlineno, co_qualname) plus `instruction_offset` in the caller. Map the call site via `co_positions` to the static call node, and the target via filename+qualname to the static function node. If the static edge exists, mark it `observed=true` with a hit count; otherwise add a new `observed`-only edge. This is how dynamic dispatch, `getattr`, plugin registries and DI containers become visible.

### Gaps
- I found no published precision/recall evaluation of pyright, ty or pyrefly used as a call-graph oracle; their accuracy for this purpose is unmeasured.
- I did not find whether PyCG/JARVIS benchmark numbers hold on FastAPI-style code (DI-heavy, async, Pydantic).
- The newer Python call-graph literature (2025–2026) beyond JARVIS was not surveyed in this pass.

---

## 5. Java and TypeScript/JavaScript tooling (later phases)

### Takeaway
- **Java:** JavaParser (+SymbolSolver), dual LGPL-3.0/Apache-2.0, is the lightest source-level option for annotations (Spring `@RequestMapping` family) and per-method CFGs. Spoon (MIT/CeCILL-C) is a richer source model. SootUp (LGPL-2.1), WALA (EPL-2.0) and OPAL (BSD-2) are bytecode-level and provide call-graph algorithms, at much higher setup cost (compiled classpath needed).
- **TypeScript:** the ecosystem is mid-migration. TypeScript 7.0 (the Go port, GA July 2026) shipped **without** a compiler API. The 7.1 beta (Oct 2026) restores it under new entry points, and ts-morph is still on TS 6.

### Cited Findings
**Java**
- **SootUp**: LGPL-2.1, v3.0.1 (2026-08-07), active. **WALA**: EPL-2.0, v1.9.0 (2026-10-30), active. — [SootUp](https://github.com/soot-oss/SootUp); [WALA](https://github.com/wala/WALA)
- **Spoon**: v11.5.0 (2026-07-14). The repo ships both `LICENSE-MIT.txt` and `LICENSE-CECILL-C.txt`. — [Spoon repo](https://github.com/INRIA/spoon)
- **JavaParser**: "available either under the terms of the LGPL License or the Apache License. You as the user are entitled to choose", 3.28.2 (2026-05-31). — [JavaParser LICENSE](https://github.com/javaparser/javaparser/blob/HEAD/LICENSE)
- **OPAL**: BSD 2-Clause (TU Darmstadt), 7.0.0 (2025-12-16), last commit 2026-07-02. — [OPAL LICENSE](https://github.com/opalj/opal/blob/HEAD/LICENSE)
- **Spring endpoint discovery:**
  - Static: Respector (ICSE 2024, Georgia Tech) uses static and symbolic analysis to generate OpenAPI v3 for Spring Boot and Jersey APIs, evaluated on 15 real APIs. — [Respector paper (NSF PAR)](https://par.nsf.gov/servlets/purl/10537946); [ICSE 2024 artifact](https://conf.researchr.org/details/icse-2024/icse-2024-artifact-evaluation/14/A-Replication-of-Generating-REST-API-Specifications-through-Static-Analysis-)
  - AutoOAS (Lercher et al.) works from bytecode, reports limitations in Respector and Prophet, and adds Spring profiles and richer data models. — [arXiv 2410.23873](https://arxiv.org/abs/2410.23873v1); [AutoOAS PDF](https://pinzger.github.io/papers/Lercher2024-AutoOAS.pdf)
  - Runtime: Spring Boot Actuator's `MappingsEndpoint` exposes all mappings at runtime. — [MappingsEndpoint.java](https://github.com/spring-projects/spring-boot/blob/HEAD/module/spring-boot-actuator/src/main/java/org/springframework/boot/actuate/web/mappings/MappingsEndpoint.java)

**TypeScript / JavaScript**
- **TypeScript compiler:**
  - The Microsoft/TypeScript repo (Apache-2.0) latest release is v7.0.2 (2026-08-20). — [TypeScript repo](https://github.com/microsoft/TypeScript)
  - TypeScript 7 GA (8 Jul 2026) shipped without an API; tools needing it had to stay on TS 6. — [InfoQ: TypeScript 7 released](https://infoq.com/news/2026/08/typescript-7-released/); [TS 7.0 announcement](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/)
  - The 7.1 beta (announced 20 Oct 2026) "restores the compiler API that 7.0 dropped". Entry points are `typescript/sync`, `typescript/async`, `typescript/fs` and `typescript/ast`, with snapshot-based incremental edits. The team says the API "will stay backward compatible across all of 7.x once stable". RC and stable were tentatively planned for late November 2026. ts-morph is named among the tools that were stranded on TS 6. — [InfoQ: TypeScript 7.1 beta](https://infoq.com/news/2026/11/typescript-7-1-beta)
- **ts-morph**: MIT, 28.0.0 (2026-04-12), last commit 2026-08-21. **Babel**: MIT, v8.1.2 (2026-11-11). — [ts-morph](https://github.com/dsherret/ts-morph); [Babel](https://github.com/babel/babel)
- **NestJS** v12.5.0 (MIT):
  - Runtime route resolution lives in `packages/core/router` (`routes-resolver.ts`, `router-explorer.ts`, `paths-explorer.ts`, `route-path-factory.ts`). — [nest core/router](https://github.com/nestjs/nest/tree/HEAD/packages/core/router)
  - `@nestjs/swagger` ships a TS compiler plugin (`lib/plugin/compiler-plugin.ts`), which is prior art for static decorator/DTO extraction. — [nestjs/swagger plugin](https://github.com/nestjs/swagger/tree/HEAD/lib/plugin)
- **Express** v5.3.0 (MIT): `app.router` is a lazily created getter backed by the standalone `router` package. Runtime introspection walks `app.router.stack`; in Express 5 it is `app.router` rather than `app._router`. — [express application.js](https://github.com/expressjs/express/blob/HEAD/lib/application.js)

### Inferences
- **Java:**
  - Start with JavaParser + JavaSymbolSolver (choose the Apache-2.0 option) for Spring annotation discovery (`@RestController`, `@RequestMapping` at class and method level, `@GetMapping`, etc.) and a source-level CFG that reuses the Python region model.
  - Add SootUp (LGPL, keep as an optional dependency) or OPAL (BSD) only for whole-program call graphs (CHA/RTA). The cost is requiring compiled classes and a resolved classpath.
  - Spring's DI (`@Autowired` interfaces with one implementation) is the Java analogue of `Depends` and needs a framework-aware resolver.
- **TypeScript:** target the TS 7.1 API for the long term and use ts-morph on TS 6 for an MVP. Alternatively, isolate the TS layer behind a small Node sidecar so the API switch is contained. For Express, use runtime `app.router.stack` introspection plus a static fallback matching `app.get(...)` / `router.use(prefix, sub)`. For NestJS, use decorators (`@Controller(prefix)`, `@Get(path)`) and module imports.
- **Cost:** Python alone is a significant effort. Each additional language needs a parser front end, a CFG lowering, a resolver and framework adapters. A shared IR and shared CFG "region" vocabulary keeps the UI language-neutral.

### Gaps
- No measured effort or cost data for building Spring/NestJS adapters was found.
- I could not find Respector's current repository or license.
- ts-morph's plans for TS 7.1 were not found.

---

## 6. tree-sitter and existing multi-language CPG backbones

### Takeaway
tree-sitter (MIT, very active) is an excellent multi-language parser for discovery and pattern matching. It gives **syntax only**: no name resolution, types or CFG, and GitHub's stack-graphs, which added name resolution on top, is archived. Of the full code-property-graph platforms:
- **Fraunhofer CPG** (Apache-2.0; Python via embedded CPython/Jep, plus Java, TypeScript, Go, C/C++ and more; EOG = statement-level evaluation order) is the best-licensed candidate for a multi-language backbone.
- **Joern** (Apache-2.0, extremely active, Python/JS/Java frontends) is the most mature query platform.
- **CodeQL** is excluded by license for closed-source enterprise use.
- **Semgrep** is LGPL-2.1.
- **Glean** (BSD) is heavyweight indexing infrastructure.

For a Python-first MVP, an in-house `ast`-based pipeline that emits a CPG-compatible IR is lower-risk than adopting a JVM backbone.

### Cited Findings
- **tree-sitter**: MIT, v0.27.2 (2026-11-07). py-tree-sitter: MIT, v0.26.1 (2026-11-09). — [tree-sitter](https://github.com/tree-sitter/tree-sitter); [py-tree-sitter](https://github.com/tree-sitter/py-tree-sitter)
- **stack-graphs**: Apache-2.0, **archived**. The README says: "This repository is no longer supported or updated by GitHub." Last commit 2025-09-09. — [stack-graphs](https://github.com/github/stack-graphs)
- **tree-sitter-based CFG libraries:** small, young projects exist. **treeloom** (PyPI) builds a "language-agnostic Code Property Graph" with FLOWS_TO and BRANCHES_TO CFG edges for Python, JS, TS, Go, Java, C, C++ and Rust via tree-sitter; CFG edges arrived in v0.2.2. forgekit-core extracts CFGs for C, Java and Rust only. — [treeloom on PyPI](https://pypi.org/project/treeloom/); [forgekit-core docs](https://docs.rs/forgekit-core/0.2.2/forge_core/treesitter)
- **Joern**:
  - License and activity: Apache-2.0, v4.0.681 released on 2026-11-12 (near-daily releases).
  - Frontends: abap2cpg, c2cpg, csharpsrc2cpg, ghidra2cpg, gosrc2cpg, javasrc2cpg, jimple2cpg, jssrc2cpg, kotlin2cpg, php2cpg, **pysrc2cpg**, rubysrc2cpg, rust2cpg, swiftsrc2cpg.
  - Sources: [Joern repo](https://github.com/joernio/joern); [frontends dir](https://github.com/joernio/joern/tree/HEAD/joern-cli/frontends)
- **Fraunhofer CPG**:
  - License and version: Apache-2.0, v11.0.4 (2026-10-30).
  - Modules: cpg-language-{python, java, jvm, typescript, go, cxx, llvm, ruby, rust, ini}, cpg-analysis, cpg-concepts, cpg-neo4j, cpg-serialization, cpg-ai, and the Codyze tools.
  - Python frontend: declares `implementation(libs.jep)` ("jep for python support") and has a `JepSingleton.kt`. It drives a real CPython interpreter, so the host Python's own `ast` parses the code.
  - Sources: [cpg repo](https://github.com/Fraunhofer-AISEC/cpg); [cpg-language-python build.gradle.kts](https://github.com/Fraunhofer-AISEC/cpg/blob/HEAD/cpg-language-python/build.gradle.kts); [specs: EOG, DFG, PDG, overlays, inference](https://fraunhofer-aisec.github.io/cpg/CPG/specs)
- **CodeQL**:
  - The github/codeql repo (queries and libraries) is MIT. The CodeQL CLI is under the GitHub CodeQL Terms: per-user, allowing academic research, demonstration, and analysis of OSI-licensed code (CI/CD only if hosted on GitHub.com).
  - Closed-source analysis needs a separate commercial license or GitHub Advanced Security.
  - Sources: [CodeQL license (Security Lab)](https://securitylab.github.com/tools/codeql/license); [ScanCode copy of 2020 terms](https://scancode-licensedb.aboutcode.org/github-codeql-terms-2020.html); [About the CodeQL CLI](https://docs.github.com/en/enterprise-server@3.9/code-security/codeql-cli/getting-started-with-the-codeql-cli/about-the-codeql-cli)
- **Semgrep**: LGPL-2.1, v1.185.0 (2026-11-10). **Glean** (Meta): "BSD License For Glean software", last commit 2026-11-12. — [semgrep](https://github.com/semgrep/semgrep); [Glean LICENSE](https://github.com/facebookincubator/Glean/blob/HEAD/LICENSE)
- **ast-grep** (tree-sitter-based structural search): MIT, 0.51.2 (2026-11-11). — [ast-grep](https://github.com/ast-grep/ast-grep)

### Inferences
- **Is tree-sitter enough for CFG?** For parsing, yes: it is error-tolerant and incremental, and grammars cover all target languages. For CFG you still hand-write a lowering per language, since the grammar node names differ. For call resolution, no: there is no scoping or type info, and stack-graphs is abandoned. tree-sitter is a good choice for: (a) fast endpoint discovery and decorator matching across Python/Java/TS (via ast-grep-style patterns), (b) partial or broken files in the editor, (c) a uniform syntax layer for TS/Java before heavier semantic tools are added.
- **Backbone options:**
  - (A) **In-house IR + per-language front ends** (Python `ast` now; JavaParser and TS API later). Light, Python-native, full control over "readable nodes". This is the recommended route for the MVP.
  - (B) **Fraunhofer CPG as the backbone** (JVM/Kotlin service). Apache-2.0, already multi-language including Python and TypeScript, and the EOG is close to readable nodes. Costs: a JVM dependency, Jep/CPython embedding complexity, a smaller community (473 stars), and framework adapters still needed.
  - (C) **Joern**. Apache-2.0 and very mature, but Scala/JVM-heavy, security-query oriented, and its Python frontend is a custom parser whose 3.12+ coverage is unverified.
  - Not recommended: CodeQL (license), Semgrep (LGPL; also oriented to matching rather than graph export), Glean (infrastructure-heavy), stack-graphs (archived).
- Design the EasyAPI IR so it can be **produced from** a Fraunhofer CPG or Joern export later (`kind` maps to node labels; edge kinds map to CFG/CALL/AST/CONDITION). That keeps option B/C open without committing now.

### Gaps
- Joern pysrc2cpg's coverage of `match`, `except*` and PEP 695 was not verified. GitHub code search for `match_stmt` / `MatchCase` in pysrc2cpg returned nothing, which is inconclusive.
- I did not find whether Fraunhofer CPG's Python frontend fully supports 3.12–3.14 constructs, or how its EOG handles `match`.
- Glean's Python indexing story was not researched.
- treeloom's maturity and license were not verified beyond its PyPI listing.

---

## 7. Language-neutral graph IR: fields used by existing IRs and a recommended minimal JSON schema

### Takeaway
Existing schemas converge on a small common core:
- Typed nodes with code text and a line/column range.
- Ordered AST children.
- Typed edges (AST / CFG / CALL / CONDITION / control and data dependence).
- A qualified-name identity for functions (Joern FULL_NAME, SCIP symbol, SARIF fullyQualifiedName).
- Optional provenance, such as SARIF `codeFlows`/`threadFlowLocation` with `executionOrder`/`state` for observed paths.

EasyAPI should use a JSON schema with hierarchical regions (for collapsible n8n-like rendering) and explicit edge provenance (static, inferred or observed).

### Cited Findings
- **Joern CPG 1.1:**
  - Every AST node has CODE, LINE_NUMBER, COLUMN_NUMBER and ORDER.
  - METHOD has FULL_NAME, SIGNATURE, IS_EXTERNAL, FILENAME, HASH, LINE_NUMBER_END, COLUMN_NUMBER_END and AST_PARENT_FULL_NAME. CALL has METHOD_FULL_NAME, DISPATCH_TYPE, SIGNATURE, ARGUMENT_INDEX and ARGUMENT_NAME. CONTROL_STRUCTURE has CONTROL_STRUCTURE_TYPE.
  - Edge types: AST, CFG, CDG, CALL, ARGUMENT, RECEIVER, CONDITION, REACHING_DEF (with property VARIABLE), DOMINATE/POST_DOMINATE, REF, SOURCE_FILE and TAGGED_BY.
  - TAG nodes (NAME, VALUE) support arbitrary annotations.
  - Source: [Joern CPG schema](https://cpg.joern.io/)
- **Fraunhofer CPG** layers its specs as AST, EOG (evaluation order), DFG (data flow, with function summaries), PDG, inference and "overlays". — [Fraunhofer CPG specs](https://fraunhofer-aisec.github.io/cpg/CPG/specs)
- **SARIF 2.1.0** — [SARIF 2.1.0 JSON schema](https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json)
  - `region`: startLine, startColumn, endLine, endColumn, charOffset, charLength, byteOffset, byteLength, snippet, message, sourceLanguage.
  - `physicalLocation`: address, artifactLocation, region, contextRegion.
  - `logicalLocation`: name, index, fullyQualifiedName, decoratedName, parentIndex, kind.
  - `location`: id, physicalLocation, logicalLocations, message, annotations, relationships.
  - `codeFlow`: message, threadFlows.
  - `threadFlowLocation`: index, location, stack, kinds, taxa, module, state, nestingLevel, **executionOrder**, **executionTimeUtc**, importance, **webRequest**, **webResponse**.
- **SCIP:**
  - Symbol grammar: `<symbol> ::= <scheme> ' ' <package> ' ' (<descriptor>)+ | 'local ' <local-id>`, with `<package> ::= <manager> ' ' <package-name> ' ' <version>` and descriptors for namespace, type, term, method, type-parameter, parameter, meta and macro.
  - `Occurrence` messages carry ranges, `enclosing_range` and a `SymbolRole` bitset.
  - The repo now lives at scip-code/scip (Apache-2.0, v0.10.0, 2026-09-03).
  - Source: [scip.proto](https://github.com/scip-code/scip/blob/HEAD/scip.proto)

### Inferences: recommended minimal schema (v0)
```json
{
  "schema": "easyapi.graph/0.1",
  "snapshot": { "id": "sha256-of-inputs", "vcs": {"commit": "abc123", "dirty": false},
                "language": "python", "producedBy": {"tool": "easyapi-py", "version": "0.1.0"} },
  "files":   [ { "id": "f1", "path": "app/routers/users.py", "sha256": "…" } ],
  "nodes": [
    { "id": "py:app.routers.users:get_user#/body/2/if",       // stable id (section 8)
      "kind": "condition",                // endpoint | function | code | call | condition | switch | case
                                          // loop | try | handler | finally | with | return | raise
                                          // yield | await | dependency | middleware | exception_handler
                                          // background_task | external | unresolved | entry | exit
      "label": "user is None",            // short human text
      "code": "if user is None:",         // exact source snippet (≤ N chars)
      "loc": { "file": "f1", "startLine": 42, "startCol": 4, "endLine": 43, "endCol": 40 },
      "parent": "py:app.routers.users:get_user",   // region containment (collapsible subgraphs)
      "order": 2,
      "symbol": null,                     // for function/endpoint: qualified name or SCIP-like symbol
      "attrs": { "async": false, "http": null, "tags": [] },
      "contentHash": "sha1-of-normalized-ast-subtree"
    }
  ],
  "edges": [
    { "id": "e1", "src": "…#/body/2/if", "dst": "…#/body/2/if/body/0/raise",
      "kind": "true",                     // next | true | false | case | default | loop_body | loop_back
                                          // loop_exit | loop_else | exception | finally | return | raise
                                          // call | dependency | middleware_next | background | yield_resume
      "label": null,
      "provenance": { "source": "static", // static | inferred | observed
                      "resolver": "ast",  // ast | pyright@1.1.414 | framework:fastapi | runtime
                      "confidence": 1.0,
                      "candidates": null },   // for call edges with several possible targets
      "observed": { "count": 0, "lastSeen": null }  // filled by the runtime merger
    }
  ]
}
```
- Keep **AST containment (`parent`)** separate from **flow edges**. The UI collapses regions using `parent`, and edges crossing a collapsed region boundary are re-attached to the region node.
- Every endpoint gets synthetic `entry`/`exit` nodes, and every function gets an `exit` and a `raise-exit`. This mirrors Joern's METHOD / METHOD_RETURN pairing.
- `kind` vocabulary is language-neutral. Language-specific details go in `attrs`, e.g. `{"python": {"except_star": true}}`.
- The schema should be exportable to SARIF `codeFlows` (for an observed request path) and importable from Joern / Fraunhofer CPG exports (`kind` ↔ node label, `edges.kind` ↔ CFG/CALL/CONDITION).

### Gaps
- I did not find an existing open "flowchart IR" standard aimed at UI rendering; the schema above is a synthesis.
- The LSIF format (the predecessor of SCIP) was not reviewed.

---

## 8. Mapping static nodes to runtime events, stable IDs, and versioning

### Takeaway
Python 3.12+ exposes everything needed to map runtime events onto static nodes with exact positions:
- `sys.monitoring` (since 3.12) delivers per-code-object events with `instruction_offset` and `destination_offset` for branches and jumps. 3.14 split branch events into `BRANCH_LEFT`/`BRANCH_RIGHT`.
- `code.co_positions()` (3.11+) maps each instruction to `(start_line, end_line, start_col, end_col)`.

Matching that 4-tuple against `ast` node spans (also UTF-8 byte columns) recovers the AST node and hence the IR node. Stable IDs should be **semantic paths** (qualname + structural AST path), not line numbers. Content hashes detect drift.

### Cited Findings
- **`sys.monitoring`** — [sys.monitoring (3.14)](https://docs.python.org/3.14/library/sys.monitoring.html); [3.14 doc source](https://sources.debian.org/src/python3.14/3.14.3-1/Doc/library/sys.monitoring.rst)
  - History: added in Python 3.12. In 3.14, `BRANCH` was deprecated in favour of `BRANCH_LEFT`/`BRANCH_RIGHT`, which "can be disabled independently" for much better performance, and `clear_tool_id()` was added.
  - Local events (per code location, can return `DISABLE`): PY_START, PY_RESUME, PY_RETURN, PY_YIELD, CALL, LINE, INSTRUCTION, JUMP, BRANCH_LEFT, BRANCH_RIGHT, STOP_ITERATION.
  - Other events: RAISE, EXCEPTION_HANDLED, PY_UNWIND, PY_THROW (plus RERAISE).
  - Callback signatures:
    - BRANCH_LEFT/RIGHT and JUMP: `func(code, instruction_offset, destination_offset)`.
    - CALL: `func(code, instruction_offset, callable, arg0)`.
    - RAISE and related: `func(code, instruction_offset, exception)`.
    - PY_RETURN/PY_YIELD: `func(code, instruction_offset, retval)`.
    - LINE: `func(code, line_number)`.
  - "There is no guarantee which branch is 'left' and which is 'right', except that it will be consistent for the duration of the program."
  - Returning `DISABLE` turns an event off for that location only, which matters for low overhead.
  - Predefined tool IDs: DEBUGGER_ID=0, COVERAGE_ID=1, PROFILER_ID=2, OPTIMIZER_ID=5.
- **`codeobject.co_positions()`** (added 3.11) — [Python data model: code objects](https://docs.python.org/3.14/reference/datamodel.html)
  - Yields `(start_line, end_line, start_column, end_column)` per code unit. Columns are "0-indexed utf-8 byte offsets on the given source line".
  - Elements may be `None` under `-X no_debug_ranges` / `PYTHONNODEBUGRANGES`, for pycs compiled that way, and for artificial instructions.
- **`co_lines()`** (3.10, PEP 626) yields `(start, end, lineno)` bytecode ranges. `co_lnotab` is deprecated since 3.12 and may be removed in 3.15. — [Python data model: code objects](https://docs.python.org/3.14/reference/datamodel.html)
- **PEP 709** (3.12) inlines list, dict and set comprehensions into the enclosing code object, so their events arrive under the parent function. — [PEP 709](https://peps.python.org/pep-0709/)
- **Identity schemes in existing IRs:** SCIP symbols are package+version+descriptor strings ([scip.proto](https://github.com/scip-code/scip/blob/HEAD/scip.proto)). Joern METHOD nodes carry FULL_NAME, SIGNATURE and HASH ([Joern CPG schema](https://cpg.joern.io/)).

### Inferences
- **Stable node ID recipe:**
  - Format: `"{lang}:{module_qualname}:{function_qualname}#{ast_path}"`.
  - `ast_path` is the chain of `(field, index, kind)` from the function root, e.g. `/body/2/If/orelse/0/Return`.
  - Function and endpoint IDs use only module + qualname (`co_qualname`-compatible, e.g. `UserService.get.<locals>.helper`), so they survive edits elsewhere in the file.
  - Also store `contentHash` (a hash of the normalized AST subtree without positions) and the `loc`.
  - On re-analysis: (1) match by ID; (2) if the ID is missing, match by `contentHash` within the same function (handles moved statements); (3) otherwise fall back to a GumTree-style tree diff, or mark the old node "removed" and orphan its runtime stats.
- **Versioning:** key every graph snapshot by VCS commit + dirty-hash and by the hash of each file. Store runtime observations against `(snapshot_id, node_id)`. When the snapshot changes, carry observations forward only for nodes whose `contentHash` is unchanged, and flag the rest "stale".
- **Runtime mapping algorithm for Python:**
  1. At analysis time, for each function, build an interval index from `ast` node spans `(lineno, col_offset, end_lineno, end_col_offset)` to IR node IDs. The `ast` docs define `col_offset` as a UTF-8 byte offset, matching `co_positions`.
  2. At runtime, cache per code object a table `instruction_offset → co_positions tuple → innermost enclosing AST node → IR node`.
  3. For `BRANCH_LEFT/RIGHT(code, off, dest)`, map `off` to the condition node and `dest` to the first node of the taken successor. Comparing that with the static true/false successors labels the edge as observed. This sidesteps the unspecified left/right semantics.
  4. For `CALL`, map the call site via `off` and the target via `callable.__code__` (co_filename, co_qualname, co_firstlineno), then merge into the call-edge provenance (section 4).
  5. For `RAISE`/`EXCEPTION_HANDLED`/`PY_UNWIND`, record exception-edge traversal from the raising node to the handler, or out of the function.
  6. Return `DISABLE` after the first hit per location when only coverage is wanted (cheap "was this path taken"). Re-enable with `restart_events()` per request window when counts are needed.
- **Practical pitfalls:**
  - `-X no_debug_ranges` or pycs compiled that way remove column data; detect this and fall back to line-level mapping.
  - Decorators and wrappers (`functools.wraps`) mean the CALL `callable` may be the wrapper; unwrap via `__wrapped__`.
  - Async functions and generators produce PY_YIELD/PY_RESUME pairs that map to `await`/`yield` nodes.
  - Under PEP 709, comprehensions report against the parent code object, which suits the "comprehension stays inside parent node" display rule.

### Gaps
- I did not find any published tool that implements AST-node-level runtime mapping via `co_positions` plus `sys.monitoring` for visualization. Coverage tools (coverage.py's sys.monitoring core) are the closest prior art but were not reviewed here.
- The overhead of BRANCH_LEFT/RIGHT plus CALL monitoring under production load was not measured or found; the docs only describe the relative benefit of DISABLE.
- `co_branches()` (if present in 3.14) was not documented in the portion of the data-model page that was read.
- Equivalent runtime-to-static mapping for Java (JVMTI/JFR, bytecode line tables) and Node (V8 inspector coverage) was not researched.
