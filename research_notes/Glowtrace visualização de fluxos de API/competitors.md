# Competitive landscape: tools that visualize backend API code as flows and/or record per-request execution (as of Nov 2026)

Scope reminder: Glowtrace = drop-in FastAPI library that (a) statically maps every endpoint into an n8n-style node graph (calls, if/else, for/while, try/except, return/raise) and (b) records each real request and overlays it on that graph (branches taken, args/returns per node, where an exception stopped the flow). Star counts and "last push" dates below come from the GitHub REST API queried on 2026-11-12, unless noted otherwise. PyPI versions and dates come from the PyPI JSON API on the same day.

## 1. AppMap (appmap-python / appmap-java / appmap-js / appmap-node): what it records, how it visualizes, branch-level detail, license, company status

### Takeaway
AppMap is the closest established open-source-ish product to Glowtrace's runtime half. It records function-level traces per HTTP request, including parameters, return values, exceptions, SQL and HTTP server requests, with FastAPI support. It renders them as dependency maps, sequence diagrams, trace views and flame graphs. It does **not** record or draw intra-function branches or loops, and it has no static control-flow graph. Its agents are under **MIT + Commons Clause**, which is not OSI open source. Repos were still actively maintained in Nov 2026, and I found no acquisition or shutdown news.

### Cited Findings
- **License:** the appmap-python LICENSE file starts with the Commons Clause condition: "the License does not grant to you, the right to Sell the Software", where "Sell" includes fees for hosting or consulting. The underlying license is MIT. — [appmap-python LICENSE](https://raw.githubusercontent.com/getappmap/appmap-python/master/LICENSE)
- **License metadata conflicts:**
  - The GitHub API reports `NOASSERTION` for appmap-python, appmap-java and appmap-node, and no license for appmap-js. The VS Code extension (vscode-appland) is plain MIT. — [GitHub getappmap org](https://github.com/getappmap)
  - The PyPI metadata for `appmap` 4.0.0 says only "MIT", while the repo LICENSE carries the Commons Clause. — [PyPI appmap](https://pypi.org/project/appmap/)
- **What it records:** the Python agent's data includes "trace events (function calls, web services, RPC calls, SQL, parameters, return values, exceptions, etc)", plus code structure (modules, classes, methods) and metadata. — [AppMap Python reference](https://appmap.io/docs/reference/appmap-python.html)
- **Granularity:** each function is instrumented so that a trace event is added when it is called. The docs describe recording only at function level. Branches, loops and individual lines are not mentioned. — [AppMap Python reference](https://appmap.io/docs/reference/appmap-python.html)
- **Supported frameworks (Python):**
  - Web: Django >=3.2,<7; Flask ~2/~3; **FastAPI >=0.110,<1**; uvicorn >=0.27.
  - Tests: pytest ~7 and unittest.
  - Database: SQLAlchemy ~1.4/~2.
  - Source: [AppMap Python reference](https://appmap.io/docs/reference/appmap-python.html)
- **Recording modes:**
  - Per-request recording (`APPMAP_RECORD_REQUESTS`).
  - Remote recording, automatic in dev (FastAPI under `uvicorn --reload`).
  - One recording per pytest/unittest test.
  - Whole-process recording.
  - Code-block recording via the `appmap.record` context manager.
  - The doc also says AppMap is "enabled by default for now" and will be disabled by default "in version 2". The current PyPI version is 4.0.0, so that page may be stale.
  - Sources: [AppMap Python reference](https://appmap.io/docs/reference/appmap-python.html); [PyPI appmap 4.0.0, 2026-11-10](https://pypi.org/project/appmap/)
- **Visualizations:** Sequence Diagrams, Dependency Maps, Flame Graphs and Trace Views. Flame graphs were added to the VS Code and JetBrains extensions in July 2023, together with sequence-diagram filtering. — [AppMap dev.to: Introducing Flame graphs](https://dev.to/appmap/introducing-flame-graphs-its-getting-hot-in-here-1j9l); [Forgepoint summary](https://forgepointcap.com/perspectives/appmap-announces-a-new-filtering-feature-of-its-sequence-diagram-tool-and-that-flame-graphs-are-now-available-within-the-appmap-extension-for-vs-code-and-jetbrains-editors-like-intellij)
- **Recorded data includes** function calls, return values, exceptions, HTTP requests/responses and SQL queries (secondary summary). — [khanate.gitbook.io AppMap overview](https://khanate.gitbook.io/blog/learn/appmap)
- **Runtime Code Review:** released as a GitHub Action in Nov 2023. Press described AppMap as working with Rails, Django, Flask, Express and Spring. — [The New Stack](https://thenewstack.io/appmap-releases-runtime-code-review-as-a-github-action/); [SiliconANGLE, 2023-11-07](https://siliconangle.com/2023/11/07/appmap-integrates-code-visualization-runtime-analysis-tools-github/)
- **Maintenance as of Nov 2026:**

  | Repo | Stars | Last push |
  |---|---|---|
  | appmap-python | 104 | 2026-11-10 |
  | appmap-java | 88 | 2026-10-27 |
  | appmap-js | 55 | 2026-11-11 |
  | appmap-node | 13 | 2026-11-01 |
  | vscode-appland | 160 | 2026-11-11 |

  The org has 69 repositories. — [GitHub getappmap org](https://github.com/getappmap)
- **Company status:** searches found no 2025–2026 news of an acquisition, layoffs or new funding for AppMap. "AppLand AB", acquired by OnMobile in 2018, is an unrelated Swedish app-store company. — [CB Insights "AppLand"](https://www.cbinsights.com/company/appland) (shows the name collision)

### Inferences
- AppMap already covers about 60% of Glowtrace's runtime vision for FastAPI: per-request recording, args, returns, exceptions and SQL. Glowtrace's differentiators against it are:
  - an intra-function CFG (if/else/loop/try nodes and which edge was taken);
  - a static "every endpoint" graph that exists before any request runs;
  - an n8n-style canvas instead of sequence or trace views;
  - a truly OSI-approved license (MIT/Apache without Commons Clause).
- The Commons Clause stops third parties from selling hosted AppMap services. A permissive Glowtrace could be embedded by vendors in ways AppMap cannot.
- Low GitHub stars (around 100 per agent) despite years of existence suggest limited community pull for the agents. Most users likely reach AppMap through the IDE extension.

### Gaps
- No official 2025–2026 statement on AppMap/AppLand Inc. funding, headcount or strategy was found. Its "Navie" AI assistant was not verified in this session.
- Whether AppMap's newer versions (3.x/4.x) record outgoing HTTP client requests in Python was not confirmed. The docs page only discusses server requests.
- Pricing for AppMap's commercial tiers was not retrieved.

## 2. Runtime/live debuggers & code-level observability: which show function-level or branch-level flow per request?

### Takeaway
None of the commercial observability or live-debugging vendors shows a **branch-level** (if/else/loop) flow per request. The finest commercial granularity found is:
- function-level spans that you add yourself (Sentry, OTel);
- line-level snapshots or logpoints captured on demand or on exception (Datadog Live Debugger, Exception Replay, Dynamic Instrumentation; Lightrun; Rookout, now Dynatrace);
- aggregated function-level call graphs (Hud).

The category has consolidated heavily:
- Rookout went to Dynatrace (2023).
- Helios went to Snyk (2024).
- Digma shut down (Nov 2025).
- Lumigo went to Dash0 (2026).
- Lightrun raised $70M (2025) and pivoted toward "AI SRE".

### Cited Findings
- **Lightrun:**
  - Raised a $70M Series B on 2025-04-28, led by Accel and Insight Partners, for $110M total. The core product is the "Runtime Autonomous AI Debugger". — [Lightrun press release](https://lightrun.com/press/lightrun-secures-70m-series-b-to-redefine-software-resilience-and-shape-the-future-of-autonomous-application-remediation/); [SiliconANGLE](https://siliconangle.com/2025/04/28/lightrun-raises-70m-use-ai-real-time-enterprise-software-observability-remediation)
  - Its revenue reportedly grew 4.5x after the July 2024 debugger launch. This is a company claim. — [Dataconomy](https://dataconomy.com/2025/04/28/lightrun-raises-70-million-usd-to-fix-your-code-before-it-breaks)
  - CB Insights says Lightrun was recognized in the 2026 Gartner Market Guide for AI SRE Tooling. — [CB Insights](https://www.cbinsights.com/company/lightrun)
  - Its public GitHub repo is tiny: 24 stars, last push 2024-09-22, Apache-2.0. The product is proprietary. — [GitHub lightrun-platform/lightrun](https://github.com/lightrun-platform/lightrun)
- **Rookout → Dynatrace:**
  - Dynatrace announced on 2023-07-31 a definitive agreement to acquire Rookout, which does live code debugging for running cloud-native apps without restarts. — [Dynatrace IR](https://ir.dynatrace.com/news-events/press-releases/detail/303/dynatrace-to-acquire-rookout-to-deliver-code-debugging-in)
  - The price was undisclosed, and Rookout had raised about $28M. — [TechCrunch](https://techcrunch.com/2023/07/31/dynatrace-acquires-cloud-native-debugging-platform-rookout/)
- **Helios → Snyk:**
  - Snyk announced in Jan 2024 that it was acquiring Helios, a "runtime data pioneer". The runtime data feeds Snyk AppRisk (ASPM). — [Snyk news](https://snyk.io/news/snyk-acquires-runtime-data-pioneer-helios); [Snyk blog](https://snyk.io/blog/welcoming-helios-to-snyk)
  - Reported as a cash-stock deal worth "tens of millions" of USD. — [Globes](https://en.globes.co.il/en/article-snyk-buys-israeli-runtime-data-co-helios-1001467857)
  - In effect, Helios is no longer a standalone developer tool. It was folded into security posture management.
- **Digma:**
  - Startup databases list it as having ceased operations in Nov 2025. — [Startup Nation Central](https://finder.startupnationcentral.org/company_page/digma)
  - Its site has a "We're sad to see you go" page. — [digma.ai](https://digma.ai/?p=2203)
  - It had raised a $6M seed in 2023. — [JPost](https://jpost.com/business-and-innovation/tech-and-start-ups/article-760495)
- **Lumigo:**
  - Dash0 announced on 2026-02-04 that it had acquired Lumigo, the serverless/AWS observability vendor. Terms were not disclosed. — [Dash0 blog](https://dash0.com/blog/dash0-acquires-lumigo-to-expand-agentic-observability-across-aws-and-serverless); [Dash0 Lumigo FAQ](https://www.dash0.com/lumigo-acquisition-faq)
- **Datadog:**
  - **Code Origin for Spans:** links spans to the source line that created them. Users can click source variables in the IDE to add them as span attributes on future spans, via Dynamic Instrumentation. Supports Java and Python (Python SDK 2.15.0+; Django, Flask, Starlette and derivatives) in IntelliJ and VS Code. — [Datadog Code Origin docs](https://docs.datadoghq.com/tracing/code_origin/)
  - **Dynamic Instrumentation:** requires Python >=3.10. Not compatible with Azure App Services or serverless. — [Datadog Dynamic Instrumentation](https://docs.datadoghq.com/tracing/dynamic_instrumentation/)
  - **Exception Replay:** GA for Python, Java, .NET and PHP. It captures execution context and local variable values when an exception occurs. Python is limited to about 1 snapshot per exception type per instance per hour, and some runtimes capture only on the 2nd occurrence. — [Datadog Exception Replay](https://docs.datadoghq.com/error_tracking/backend/exception_replay/)
  - **Live Debugger:** announced 2024-06-26 in beta. It lets you step through production code and see local variable values from an exception, adds AI root-cause hypotheses, "visualizes data flows between services", and generates tests from production data. — [Datadog press release](https://www.datadoghq.com/about/latest-news/press-releases/datadog-live-debugger-streamlines-troubleshooting-and-bug-resolution-with-live-production-data/)
  - dd-trace-py repo: 654 stars, license NOASSERTION (custom). — [GitHub DataDog/dd-trace-py](https://github.com/DataDog/dd-trace-py)
- **Sentry:**
  - Function-level spans need manual opt-in, either through `functions_to_trace` (a list of qualified names in `sentry_sdk.init`) or the `@sentry_sdk.trace` decorator. Newer "streamed spans" use `sentry_sdk.traces.trace`. — [Sentry Python custom instrumentation](https://docs.sentry.io/platforms/python/tracing/instrumentation/custom-instrumentation); [Sentry streamed spans](https://docs.sentry.io/platforms/python/tracing/streamed-spans/)
  - sentry-python SDK: MIT, 2.2k stars. The getsentry/sentry server has 45.8k stars, and the GitHub API reports its license as NOASSERTION (custom license). — [GitHub getsentry/sentry-python](https://github.com/getsentry/sentry-python); [GitHub getsentry/sentry](https://github.com/getsentry/sentry)
- **Hud (hud.io), a "Runtime Code Sensor":**
  - Collects function-level invocation counts, durations and line-level exceptions for every endpoint, queue and function.
  - Builds an **aggregated** call graph over time instead of distributed tracing, with a self-reported 1–2% overhead.
  - Uses a custom sensor, not OpenTelemetry.
  - Collects runtime metadata only (function names, files, durations, errors) and scrubs sensitive data.
  - Shows IDE overlays ("Hudders") in VS Code and JetBrains, plus an MCP server for coding agents.
  - Sources: [Hud FAQ](https://docs.hud.io/docs/faq); [Introducing Hud](https://www.hud.io/introducing-hud); [What you can do with Hud](https://docs.hud.io/docs/what-you-can-do-with-hud)
  - Languages: Node.js and Python, with Java, Kotlin and Go "coming soon". Launch announced 2025-12-10. — [Webull/PR news](https://www.webull.com/news/14002963577545728); [ClickHouse blog](https://clickhouse.com/blog/hud-runtime-code-sensor)
- **Multiplayer (multiplayer.app):**
  - "Full-stack session recordings" correlate frontend screens with backend traces, logs, metrics and request/response content and headers.
  - The Node SDK is built on OpenTelemetry. The company claims there is no sampling.
  - Recordings can be opened in VS Code, and the data is pitched as context for AI coding tools.
  - Sources: [npm session-recorder-node](https://socket.dev/npm/package/@multiplayer-app/session-recorder-node); [Multiplayer homepage mirror](https://hn.jakechampion.name/reader/https://www.multiplayer.app/); [Multiplayer blog: zero sampling](https://www.plushcap.com/content/multiplayer/blog/multiplayer-dont-lose-the-trace-that-matters-multiplayers-zero-sampling-approach)
- **Pyroscope (Grafana):** "Continuous Profiling Platform. Debug performance issues down to a single line of code". AGPL-3.0, 11.7k stars, active. — [GitHub grafana/pyroscope](https://github.com/grafana/pyroscope)
- **Jaeger and Tempo:**
  - Jaeger (CNCF): Apache-2.0, 23.4k stars, active. — [GitHub jaegertracing/jaeger](https://github.com/jaegertracing/jaeger)
  - Grafana Tempo: AGPL-3.0, 5.6k stars, active. — [GitHub grafana/tempo](https://github.com/grafana/tempo)

### Inferences
- **Commercial tools are blind below the span or function boundary.** They show service- or span-level waterfalls. Datadog and Lightrun let you pull line-level variable snapshots on demand, but none renders "this request took the `else` branch at line 42" as a graph. Glowtrace's branch overlay is unoccupied territory in this category.
- **The market is moving to "runtime context for AI agents"** (Hud MCP, Lightrun AI SRE, Multiplayer, Datadog AI hypotheses). An Glowtrace JSON trace format plus an MCP or agent-readable export would align with this trend.
- **Overhead and privacy are the main constraints** vendors design around:
  - Hud collects metadata only.
  - Datadog rate-limits snapshots and redacts values.
  - Kolo and routeflow are dev-only (see Q3/Q5).
  - Glowtrace capturing full args/returns for every request will need sampling, redaction and a dev-vs-prod split.

### Gaps
- **Sentry Seer:** no source was retrieved on whether Seer uses code-level traces or offers any flow visualization.
- **Honeycomb:** not researched in this session. It is believed to offer trace waterfalls and BubbleUp only, with no function or branch view, but this is unverified.
- **Pricing:** no pricing figures were retrieved for Lightrun, Datadog Live Debugger, Hud or Multiplayer.
- **Helios after Snyk:** whether Helios's standalone trace-visualization product still exists post-acquisition was not confirmed.
- **Pyroscope span profiles:** the "span profiles" feature (linking traces to profiles) was not verified in this session.

## 3. Python tracing / time-travel tools: which offer graph or flow visualization of data moving between functions?

### Takeaway
The Python tracing ecosystem is rich but split into separate kinds of tool:
- **timeline tracers:** VizTracer (Perfetto timeline with args, returns and exceptions);
- **text loggers:** PySnooper, snoop, hunter;
- **source-overlay debuggers:** birdseye (values of every evaluated expression);
- **dataflow graphs:** Cyberbrain, which is the only one that visualizes how variables flow, but is dormant since 2021–2022;
- **time-travel debuggers:** CodeTracer is active (AGPL), and Replay.io pivoted away from devtools.

Kolo is the closest per-request backend analogue. It is Django-only and proprietary, and it has repositioned as a "text-based Python debugger for AI agents". None of these tools produces an endpoint-centric node graph with branch overlay.

### Cited Findings
- **VizTracer:**
  - Logs function arguments, return values, raised exceptions and regex-matched variables without code changes. Its UI is built on Perfetto (timeline plus source, with a "Slice Flamegraph" option). No call-graph view is mentioned.
  - Supports asyncio natively and can attach to running processes. It self-reports overhead below 1x for typical code (3–4x on recursive fib).
  - Apache-2.0, 7.8k stars, active (push 2026-11-12). PyPI 1.1.1 was released 2025-11-11.
  - Sources: [GitHub gaogaotiantian/viztracer](https://github.com/gaogaotiantian/viztracer); [PyPI viztracer](https://pypi.org/project/viztracer/)
- **pycallgraph / pycallgraph2:**
  - The original `gak/pycallgraph` (GPL-2.0, 1.9k stars) is **archived**. — [GitHub gak/pycallgraph](https://github.com/gak/pycallgraph)
  - pycallgraph2's last PyPI release is 1.1.3 (2019-07-01), and its listed GitHub repo (daneads/pycallgraph2) now returns 404. **Deprecated/abandoned.** — [PyPI pycallgraph2](https://pypi.org/project/pycallgraph2/)
  - pyramid_pycallgraph once generated a callgraph image per request for Pyramid. — [ecosyste.ms](https://awesome.ecosyste.ms/projects/github.com%2Fdisko%2Fpyramid_pycallgraph)
- **PySnooper, snoop, hunter (text loggers):**
  - PySnooper: MIT, 16.6k stars, last push 2026-06. — [GitHub cool-RR/PySnooper](https://github.com/cool-RR/PySnooper)
  - snoop: MIT, 1.46k stars, v0.6.1 released 2026-07-18. — [GitHub alexmojaki/snoop](https://github.com/alexmojaki/snoop)
  - hunter: BSD-2-Clause, 874 stars, last push 2025-08. — [GitHub ionelmc/python-hunter](https://github.com/ionelmc/python-hunter)
- **birdseye:** "Graphical Python debugger which lets you easily view the values of all evaluated expressions". MIT, 1.77k stars, v0.10.0 (2025-09-06). — [GitHub alexmojaki/birdseye](https://github.com/alexmojaki/birdseye); [PyPI birdseye](https://pypi.org/project/birdseye/)
- **Cyberbrain:**
  - Runtime tracing (explicitly "NOT static analysis") through a `@trace` decorator. It visualizes program execution and how each variable changes, with dataflow highlighting.
  - VS Code is its only frontend. It may break with VS Code breakpoints and is "NOT" meant for production.
  - Sources: [GitHub laike9m/Cyberbrain](https://github.com/laike9m/Cyberbrain)
  - Last release 0.2.3 (2021-10-10), last push 2022-12-30, 2.5k stars, MIT. **Dormant.** — [PyPI cyberbrain](https://pypi.org/project/cyberbrain/); [GitHub laike9m/Cyberbrain](https://github.com/laike9m/Cyberbrain)
- **CodeTracer (metacraft-labs):**
  - A time-traveling debugger written in Nim and Rust. Its first public release (March 2025) focused on the Noir language, with Ruby and Python recorders as separate projects. — [ethereum.org CodeTracer page](https://ethereum.org/developers/tools/codetracer/); [Show HN](https://hn.svelte.dev/item/43280615)
  - Main repo: AGPL-3.0, 1.3k stars, active (push 2026-11-12). — [GitHub metacraft-labs/codetracer](https://github.com/metacraft-labs/codetracer)
  - codetracer-python-recorder: Apache-2.0, 19 stars, active. — [GitHub codetracer-python-recorder](https://github.com/metacraft-labs/codetracer-python-recorder)
  - The trace format is a separate MIT-licensed library. — [lib.rs runtime_tracing](https://lib.rs/crates/runtime_tracing)
- **Replay.io:**
  - The CEO announced "A new direction" in July 2024, a pivot away from the devtools product. — [Replay blog: A new direction](https://blog.replay.io/a-new-direction)
  - Nut.new followed in Feb 2025, then "Replay Builder", Replay MCP (time-travel for AI agents, Apr 2026) and Replay QA (May 2026). These dates come from third-party trend reports. — [Plushcap trend report](https://www.plushcap.com/trends/reports/trend-report-2026-05-18-replay)
  - The devtools repo has 723 stars. — [GitHub replayio/devtools](https://github.com/replayio/devtools)
- **rr and Thonny:**
  - rr (record & replay for native code): 10.7k stars, active. — [GitHub rr-debugger/rr](https://github.com/rr-debugger/rr)
  - Thonny (beginner IDE with step-through visualization): MIT, 4k stars, active. — [GitHub thonny/thonny](https://github.com/thonny/thonny)
- **Kolo:**
  - Captures "every executed function call, return value, local variable, HTTP request, and more in greppable trace files", with SQL query views. It is Django-only (KoloMiddleware), with a web UI at `localhost:8000/_kolo/` and a play.kolo.app playground.
  - It now describes itself as "a text-based Python debugger for AI agents" (Kolo v3). It has 526 stars; the repo moved from kolofordjango/kolo to koloai/kolo, last push 2026-04-17.
  - Sources: [GitHub koloai/kolo](https://github.com/koloai/kolo)
  - PyPI `kolo` 3.6.1 was released 2026-10-14. Its license field reads "© Kolo", i.e. **proprietary**. — [PyPI kolo](https://pypi.org/project/kolo/)
  - Its docs now recommend the web app over the (beta) VS Code extension. — [Kolo docs](https://docs.kolo.app/en/latest/)
  - It was presented at DjangoCon EU 2022. — [DjangoCon EU 2022 talk](https://2022.djangocon.eu/pretalx.evolutio.pt/djangocon-europe-2022/talk/RFFG3Z/index.html)
- **pyinstrument and django-silk:**
  - pyinstrument (call-stack profiler with a call-tree view): BSD-3, 8k stars. — [GitHub joerick/pyinstrument](https://github.com/joerick/pyinstrument)
  - django-silk (per-request profiling and SQL inspection for Django): MIT, 5k stars. — [GitHub jazzband/django-silk](https://github.com/jazzband/django-silk)
- **mermaid-trace:** visualizes Python execution as Mermaid sequence diagrams. MIT, v0.7.1 (2026-03). — [PyPI mermaid-trace](https://pypi.org/project/mermaid-trace/)
- **callflow-tracer:** traces function-call relationships into interactive graphs, with OpenTelemetry export. MIT, v0.7.0 (2026-05-31), first release 2025-09. — [PyPI callflow-tracer](https://pypi.org/project/callflow-tracer/)
- **heartrate:** shows live line-execution counts in a browser. — [CodeCut](https://codecut.ai/heartrate-visualize-the-execution-of-a-python-program-in-real-time-2/)
- **Panopticon:** debugger-based tracer emitting Chrome trace format; alpha. — [GitHub kunalb/panopticon](https://github.com/kunalb/panopticon)

### Inferences
- Cyberbrain proved that a decorator plus a dataflow graph is compelling, but it was abandoned after 2021. A maintained, endpoint-scoped successor is an open niche.
- Kolo is the most direct per-request comparator in Python, but it is Django-only and proprietary, and it now targets AI agents (text traces). Glowtrace can position as "Kolo for FastAPI, open source, with a visual CFG".
- VizTracer's sys.settrace-style recording of args and returns is mature and fast. Glowtrace could reuse its techniques, or interoperate with it (Perfetto/Chrome trace export), instead of competing on raw tracing.
- On Python 3.12+, `sys.monitoring` (PEP 669) supports branch events cheaply. FastApi-Visualizer (Q5) already uses PEP 669 for call tracing, which makes branch-level overlay technically feasible for Glowtrace.

### Gaps
- **Pernosco (omniscient debugger on rr traces):** not researched in this session.
- **Python Tutor:** its GitHub repo (pgbovine/OnlinePythonTutor) returned 404, so its current license and openness are unverified.
- **birdseye:** whether it shows which branches executed (e.g., greying out unexecuted code) was not verified.
- **Recorder/"timetravel"/PyTrace packages:** PyPI packages such as `timetrace-debugger`, `tracesnap` and `py-tt-debug` appeared in searches but were not evaluated.

## 4. Static code-to-flow visualizers: which exist, and are any API/endpoint-centric?

### Takeaway
Static tools come in two kinds:
- **call-graph generators:** code2flow, pyan3, PyCG (archived), Crabviz, CodeViz;
- **per-function flowchart/CFG generators:** PyFlowchart, staticfg (dormant), py2cfg, the CodeVisualizer VS Code extension.

AI repo-diagram tools (GitDiagram, Swark, CodeViz's architecture view) work at module or architecture level. **Only tiny 2026 projects are endpoint-centric for FastAPI:**
- flowsegul: static per-endpoint node graph with if/for/try context lines and exception paths;
- fastapi-di-viz: dependency-injection tree.

None of them overlays runtime data.

### Cited Findings
- **code2flow:** "Pretty good call graphs for dynamic languages". MIT, 4.6k stars. Last PyPI release 2.5.1 (2023-01-08), last push 2025-07. **Low maintenance.** — [GitHub scottrogowski/code2flow](https://github.com/scottrogowski/code2flow); [PyPI code2flow](https://pypi.org/project/code2flow/)
- **pyan3:** "The Python static call graph generator… Py3.10–3.14". GPL-2.0, 463 stars, v2.9.0 (2026-10-06). **Active.** — [GitHub Technologicat/pyan](https://github.com/Technologicat/pyan); [PyPI pyan3](https://pypi.org/project/pyan3/)
- **PyFlowchart:** "Python codes to Flowcharts". MIT, 419 stars, v0.6.0 (2026-03-12). **Active.** — [GitHub cdfmlr/pyflowchart](https://github.com/cdfmlr/pyflowchart)
- **staticfg:** "Python3 control flow graph generator". Apache-2.0, 216 stars. Last release 0.9.5 (2020-06), last push 2022-08. **Dormant.** — [GitHub coetaur0/staticfg](https://github.com/coetaur0/staticfg); [PyPI staticfg](https://pypi.org/project/staticfg/)
- **py2cfg:** last PyPI release 1.0.5 (2024-12-20). — [PyPI py2cfg](https://pypi.org/project/py2cfg/)
- **PyCG:** static Python call graph generator. Apache-2.0. **Archived** (last push 2023-11). — [GitHub vitsalis/PyCG](https://github.com/vitsalis/PyCG)
- **Crabviz:** "Generate interactive call graphs for various languages". AGPL-3.0, 1.4k stars, last push 2026-09. — [GitHub chanhx/crabviz](https://github.com/chanhx/crabviz)
- **CodeVisualizer (VS Code extension):**
  - Function-level flowcharts showing "control flow, loops, and decision points" (exceptions and async are mentioned) for Python, TS/JS, Java, C++, C, Rust, Go and PHP.
  - Also draws dependency graphs. Parsing uses Tree-sitter, 100% locally.
  - Optional AI generates friendlier node labels.
  - MIT, about 700 stars.
  - Source: [GitHub DucPhamNgoc08/CodeVisualizer](https://github.com/DucPhamNgoc08/CodeVisualizer)
- **CodeViz (YC S24):**
  - VS Code extension with a call graph built from installed language servers and an AI-powered C4 architecture diagram. Launched Aug–Sep 2024.
  - Sources: [Launch HN](https://hn-svelte.vercel.app/item/41393458); [YC profile](https://www.ycombinator.com/companies/codeviz); [Product Hunt](https://www.producthunt.com/posts/codeviz-yc-s24)
- **CodeSee:**
  - GitKraken announced on 2024-05-14 that it had acquired CodeSee, folding it into the "GitKraken DevEx platform". — [GitKraken press release](https://gitkraken.com/press/gitkraken-acquires-codesee-launches-devex-platform); [SD Times](https://sdtimes.com/software-development/gitkraken-acquires-codesee-launches-new-devex-platform/)
  - A LinkedIn post claims CodeSee shut down commercial operations, but its date is ambiguous and unverified. — [LinkedIn](https://sk.linkedin.com/in/daniel-ivanyi-16845458)
- **GitDiagram:** "Visualize any GitHub codebase: free interactive architecture diagrams…". MIT, 18.9k stars, active. — [GitHub ahmedkhaleel2004/gitdiagram](https://github.com/ahmedkhaleel2004/gitdiagram)
- **Swark:** LLM-generated architecture diagrams from code. AGPL-3.0, 1.7k stars, last push 2025-03. — [GitHub swark-io/swark](https://github.com/swark-io/swark)
- **Sourcetrail:** the community fork (interactive source explorer) is GPL-3.0, 768 stars, active. — [GitHub petermost/Sourcetrail](https://github.com/petermost/Sourcetrail)
- **flowsegul (FastAPI, static):**
  - Parses Python with the AST into a **per-endpoint draggable node graph**: pan/zoom, minimap, solid arrows for args and dashed arrows for returns.
  - Each function box is folded down to lines that make calls or raise, keeping the surrounding `if/for/with/try` lines for context.
  - Traces exception paths from each `raise` to the `except` that handles it, and flags irreversible steps made before a commit.
  - No runtime tracing. 0 stars, 82 commits, no license stated, push 2026-10-26.
  - Source: [GitHub hackertehlike/flowsegul](https://github.com/hackertehlike/flowsegul)
- **fastapi-di-viz:** static graph of FastAPI's dependency-injection tree. MIT. — [PyPI fastapi-di-viz](https://pypi.org/project/fastapi-di-viz/)
- **Encore:** backend framework (MPL-2.0, 12.7k stars), described as "Infrastructure orchestration from local to your cloud". — [GitHub encoredev/encore](https://github.com/encoredev/encore)

### Inferences
- Static CFG tooling for Python is either dormant (staticfg, PyCG) or produces flowchart images detached from the web framework (PyFlowchart, CodeVisualizer). None knows what a FastAPI endpoint is, how `Depends()` chains resolve, or how to stitch callee CFGs into a per-endpoint graph.
- flowsegul is the only project found whose static concept closely matches Glowtrace's: per-endpoint node graph, control-flow context, exception paths. It is a 0-star solo project without runtime overlay, so it signals the idea is being explored rather than posing a competitive threat.
- AI diagram tools (GitDiagram, Swark, CodeViz) optimize for architecture overviews and can hallucinate. A deterministic AST-plus-runtime graph is a differentiator worth stating explicitly.

### Gaps
- Swimm (current product and pricing), Sourcegraph (code graph features), Visustin, Flowchart Fun, CodeMap and Cursor/Copilot diagram features were not researched in this session.
- Whether CodeSee's product is still available inside GitKraken was not confirmed.
- Encore's "Flow" architecture diagram and local tracing dashboard were not verified in this session. It is likely service-level, not function-level.
- The Visual Studio Magazine article (Jan 2026) on a buzzy VS Code codebase-visualization extension was seen only as a search title. — [VS Magazine](https://visualstudiomagazine.com/articles/2026/01/22/buzz-about-vs-code-extension-for-codebase-visualization.aspx?p=1)

## 5. Does any tool combine static CFG + runtime overlay + n8n-style node UI (especially for FastAPI)?

### Takeaway
**No tool found does all three for general backend code.** Fragments exist:
- **Static endpoint graph without runtime:** flowsegul.
- **Runtime per-request node graph without static CFG or branches:** routeflow, fastapi-watchtrace, FastApi-Visualizer (FastAPI); SuriLens and NodeFlow (Node.js).
- **Function-level runtime with no branches and non-node UI:** AppMap, Kolo.
- **n8n-style canvas plus per-execution traces, but only for code written in their own step/flow model:** Motia, Flyde, Node-RED (not drop-in).

A 2026 wave of tiny FastAPI "runtime flow graph" projects (all 0–few stars, v0.x) shows clear demand but no winner. Glowtrace's combination remains unoccupied: static intra-function CFG of every endpoint, plus runtime overlay of branches taken with args and returns per node, as a drop-in.

### Cited Findings
- **routeflow (FastAPI):**
  - "Real-time execution flow visualization for FastAPI applications". Decorate functions with `@track` (or `track_module`). Each request is traced (order, timing, logs, errors) and rendered live as an **interactive node graph** at `/flow/`, next to Swagger.
  - Captures call args (redactable). Exceptions are recorded and re-raised.
  - Not static: graph nodes exist only for tracked functions that ran. No branch nodes.
  - No auth, dev-only, in-memory ring buffer of 500 traces, no sampling.
  - MIT, v0.3.2 (2026-08-17), first release 2026-08-06.
  - Source: [PyPI routeflow](https://pypi.org/project/routeflow/) (repo: github.com/Shyam-Sundar-Reddy/routeflow)
- **fastapi-watchtrace (WatchTrace):**
  - "Project-aware FastAPI runtime observability tool" offering "Function-level request tracing" and a "Visual request flow graph" at `/__watchtrace/`. It uses a `code_index_path`, which suggests some pre-indexing of code.
  - Sync endpoints "may lead to incomplete or unstable traces". Requires Python 3.13+.
  - v0.0.2 (2026-05-09), MIT per PyPI page.
  - Sources: [PyPI fastapi-watchtrace](https://pypi.org/project/fastapi-watchtrace/); [GitHub HOTSONHONET/WatchTrace](https://github.com/HOTSONHONET/WatchTrace)
- **FastApi-Visualizer:**
  - Dev-time dashboard built on Python 3.12 `sys.monitoring` (PEP 669). Shows per-request nested call trees and await suspend/resume, and flags event-loop blocking, as a live flow graph at `/_viz`.
  - Args, returns and branches are not mentioned. No multi-worker support.
  - 0 stars, 27 commits, no license.
  - Source: [GitHub raushankumar1511/FastApi-Visualizer](https://github.com/raushankumar1511/FastApi-Visualizer)
- **flowsegul:** static per-endpoint node graph with control-flow context and exception paths, no runtime (details in Q4). — [GitHub hackertehlike/flowsegul](https://github.com/hackertehlike/flowsegul)
- **SuriLens (Node.js):**
  - Live execution graph with replay, payload inspector/diff and timeline. Shows which middleware, controller, DB queries and external APIs ran per request.
  - Supports Express, Fastify, Koa, NestJS and Hono. Function or branch granularity is not stated.
  - 1 star. — [DEV post](https://dev.to/sonisuryansh/surilens-an-open-source-real-time-backend-execution-visualizer-for-nodejs-101k); [GitHub sonisuryansh/surilens](https://github.com/sonisuryansh/surilens)
- **NodeFlow (Node.js/NestJS):** turns real traffic into a live runtime architecture map, local-first. — [GitHub msHamed1/node-flow](https://github.com/msHamed1/node-flow)
- **Motia:**
  - A backend framework whose Workbench draws "steps" as an interactive graph (XY Flow, WebSocket updates).
  - Every execution produces a trace with step timelines, state operations, emits and logs, viewable in the Workbench Traces UI. Requires writing code as Motia steps.
  - Sources: [Motia docs: flows & visualization](https://motia-dev-website.vercel.app/docs/concepts/flows-and-visualization); [Motia Workbench docs](https://motia-dev-website.vercel.app/docs/workbench/overview); [GitHub MotiaDev/motia](https://github.com/MotiaDev/motia)
- **Flyde:** visual programming in VS Code where "the diagram is the code". You create, edit and debug backend workflows as node diagrams. — [BrightCoding on Flyde](https://converter.brightcoding.dev/blog/flyde-the-visual-backend-tool-every-developer-needs)
- **Node-RED:** flow-based low-code tool on Node.js. — [Wikipedia Node-RED](https://en.wikipedia.org/wiki/Node-RED)
- **AppMap and Kolo** (Q1, Q3): per-request, function-level recording with args and returns. Their UIs are sequence, trace, flame or text views, not CFG node canvases. Neither shows branches. — [AppMap Python reference](https://appmap.io/docs/reference/appmap-python.html); [GitHub koloai/kolo](https://github.com/koloai/kolo)
- **Datadog Code Origin:** links spans to source lines and lets you add variables as span attributes. There is no CFG view. — [Datadog Code Origin docs](https://docs.datadoghq.com/tracing/code_origin/)

### Inferences

Capability matrix (✔ = yes, ~ = partial, ✘ = no; based on the findings above):

| Tool | Static endpoint graph | Intra-function branches (if/loop/try) | Per-request runtime | Args/returns per node | Node-canvas UI | Drop-in FastAPI | License / status |
|---|---|---|---|---|---|---|---|
| AppMap | ✘ (runtime-derived maps) | ✘ | ✔ | ✔ | ~ (dependency map) | ✔ (>=0.110) | MIT+Commons Clause; active |
| Kolo | ✘ | ✘ | ✔ | ✔ (+locals) | ✘ (web/text) | ✘ (Django) | Proprietary; active |
| routeflow | ✘ | ✘ | ✔ | ~ (args; errors) | ✔ | ✔ (decorator) | MIT; v0.3, 2026 |
| fastapi-watchtrace | ~ (code index) | ✘ (not stated) | ✔ | ? | ✔ | ✔ | MIT; v0.0.2 |
| FastApi-Visualizer | ✘ | ✘ | ✔ | ✘ | ✔ | ✔ | none; 0 stars |
| flowsegul | ✔ | ~ (context lines, exception paths) | ✘ | ~ (static arg/return arrows) | ✔ | ✔ (static) | none; 0 stars |
| CodeVisualizer / PyFlowchart / staticfg | ✘ (per function) | ✔ | ✘ | ✘ | ~ (flowchart) | ✘ | MIT / MIT / Apache |
| VizTracer | ✘ | ✘ | ✔ (per run) | ✔ | ✘ (timeline) | ~ | Apache-2.0; active |
| Cyberbrain | ✘ | ✘ | ✔ (decorated fn) | ✔ (dataflow) | ~ (graph) | ✘ | MIT; dormant |
| Datadog / Lightrun / Dynatrace | ✘ | ✘ (line snapshots on demand) | ✔ (spans) | ~ (snapshots) | ✘ | ✔ (agents) | Commercial |
| Hud | ✘ | ✘ | ✘ (aggregated) | ✘ (metadata only) | ✘ (IDE overlay) | ✔ | Commercial |
| Motia / Flyde / Node-RED | ✔ (own model) | ✘ | ✔ (Motia traces) | ~ | ✔ | ✘ (rewrite required) | OSS; active |
| **Glowtrace (planned)** | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | (planned) |

- At least four independent FastAPI request-flow projects appeared on PyPI or GitHub in 2026 (routeflow, fastapi-watchtrace, FastApi-Visualizer, flowsegul). This is strong evidence of unmet demand and also of imminent crowding. Glowtrace's moat has to be the static CFG plus branch overlay, which none of them does, together with polish and maintenance.
- routeflow's design choices preview Glowtrace's must-haves:
  - redaction API (`redact=`, `capture_args=False`);
  - explicit opt-in per module;
  - an off switch through an environment variable;
  - a clear "no auth, dev only" warning;
  - a bounded ring buffer.

### Gaps
- LangGraph Studio/LangSmith offer a graph view with per-node state for LLM agent runs, the nearest UI analogue to the "overlay run on graph" idea. They were not verified in this session; the langchain-ai/langgraph-studio repo returned 404.
- Temporal, Inngest and Windmill (durable-execution or workflow UIs with step-level history) were not checked; the GitHub API rate limit was hit.
- Star counts for Motia and Flyde could not be retrieved (rate limit).
- Absence of evidence is not proof: closed-source or very new projects may exist that searches did not surface.

## 6. What do users complain about or wish for regarding these tools?

### Takeaway
Direct HN/Reddit complaint threads about AppMap or the Python tracers were sparse. The clearest community signal is the ~Jan 2026 "Show HN: Nogic", a VS Code codebase-graph extension. Commenters raised:
- closed-source distrust;
- poor performance and crashes on big repos;
- limited language support;
- missing or incorrect edges (Django);
- noisy graphs on large codebases.

The tools' own docs reveal recurring pain points:
- sync-endpoint and async tracing instability;
- overhead and rate limits;
- privacy of captured args;
- dev-only security;
- IDE-extension fragility.

### Cited Findings
- **Show HN: Nogic** (135 points, 53 comments, about 10 months before Nov 2026). Source for all points: [HN item 46605675](https://news.ycombinator.com/item?id=46605675)
  - Closed source: "Closed source vscode extensions: not for me."
  - Performance: "very slow on a not too complex codebase"; "2 or 3 fps".
  - Crashes on a 2,000+-file project.
  - A Ruby/Rails user called it "useless in Ruby or Ruby on Rails".
  - A Django user saw imports detected but no edges drawn.
  - "The biggest challenge I find is to reduce noise".
  - Requests: expand imports in place, summarize clusters for large codebases, Open VSX availability (for Cursor), and an MCP server.
  - Alternatives mentioned: Code Canvas, Visor, Lumyst, Doxygen call graphs and LLM-made Mermaid diagrams.
- **Async and sync tracing instability:** WatchTrace warns that sync (`def`) endpoints "may lead to incomplete or unstable traces". — [PyPI fastapi-watchtrace](https://pypi.org/project/fastapi-watchtrace/)
- **Not production-ready:** FastApi-Visualizer has bounded buffers that can drop events, no multi-worker support and an unauthenticated `/_viz`, and says it is "not built for production traffic volumes". — [GitHub FastApi-Visualizer](https://github.com/raushankumar1511/FastApi-Visualizer)
- **Captured data is a security risk:** routeflow has no authentication, its traces can include unredacted args and stack traces, and it must be disabled in prod via `ROUTEFLOW_ENABLED=0`. — [PyPI routeflow](https://pypi.org/project/routeflow/)
- **Cyberbrain caveats:** may malfunction with VS Code breakpoints; "should NOT use Cyberbrain in production". — [GitHub laike9m/Cyberbrain](https://github.com/laike9m/Cyberbrain)
- **Production snapshot limits:** Datadog Exception Replay takes about 1 snapshot per exception type per instance per hour in Python, sometimes only on the 2nd occurrence. Dynamic Instrumentation is unsupported on serverless and Azure App Services. — [Datadog Exception Replay](https://docs.datadoghq.com/error_tracking/backend/exception_replay/); [Datadog Dynamic Instrumentation](https://docs.datadoghq.com/tracing/dynamic_instrumentation/)
- **IDE extensions are costly to maintain:** Kolo's docs now steer users from the beta VS Code extension to a web app at `/_kolo/`. — [Kolo docs](https://docs.kolo.app/en/latest/)
- **Overhead is a self-reported selling point:** Hud claims 1–2% overhead with metadata only, and VizTracer claims under 1x overhead for typical code but 3–4x for recursive code. — [Hud FAQ](https://docs.hud.io/docs/faq); [GitHub viztracer](https://github.com/gaogaotiantian/viztracer)

### Inferences
- **Must-haves implied by these complaints:**
  - open source with a permissive license, which counters the Nogic and AppMap Commons Clause concerns;
  - graph scalability (collapse, cluster, filter by endpoint);
  - an accurate framework model (FastAPI `Depends`, routers, middleware, background tasks);
  - a web UI before IDE plugins (the Kolo lesson);
  - first-class redaction and a prod-safe mode;
  - solid async (`async def`) and sync threadpool tracing.
- **Noise reduction is likely the hardest UX problem** for an "every endpoint, every branch" graph. Default views will probably need to collapse library or framework frames and show only project code (WatchTrace's "project-aware filtering" pitch).

### Gaps
- No substantial Reddit threads or GitHub-issue analyses about AppMap, VizTracer or Lightrun complaints were retrieved. User sentiment on pricing (Datadog, Lightrun) was not sourced in this session.
- No HN thread specifically about AppMap was found.
