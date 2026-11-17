# EasyAPI: enterprise readiness, interop standards, data protection, licensing/governance and UI stack (as of Nov 2026)

Scope note: EasyAPI is an open-source dev tool that records the execution of each web-API request (function args/returns, branches, exceptions) and renders it as an n8n-style node graph. The first users are Brazilian (energy sector and government), so LGPD applies. Stability levels are marked as [STABLE], [BETA], [ALPHA], [PREVIEW], [DEVELOPMENT] or [DEPRECATED] where the sources state them.

---

## 1. OpenTelemetry standards and interop: code attributes, spans vs events, profiles, export and correlation

### Takeaway
OTel's `code.*` attributes (`code.function.name`, `code.file.path`, `code.line.number`, `code.column.number`, `code.stacktrace`) are all **[STABLE]**. EasyAPI can tag each function node with them and export over OTLP to Jaeger, Tempo, Datadog or Honeycomb, joining the existing distributed trace through W3C `traceparent` (a W3C Recommendation). Two 2026 changes affect the design. First, OTel is **deprecating the Span Events API** (`Span.AddEvent`, `Span.RecordException`) in favour of log-based events. Second, the **Profiles signal is only in public [ALPHA]** since March 2026. So function calls should be child spans, and branch-level detail belongs in EasyAPI's own store or in log-based events, not in span events or profiles. Python OTel has no zero-code way to instrument arbitrary user functions (Java does), which leaves room for EasyAPI.

### Cited Findings
**Code semantic conventions (stability)**
- The OTel attribute registry lists five current `code.*` attributes, all **Stable**: `code.function.name` (string; the fully qualified function name without arguments, e.g. `com.example.MyHttpService.serveRequest`), `code.file.path` (string; absolute path preferred), `code.line.number` (int), `code.column.number` (int), and `code.stacktrace` (string in the runtime's natural format, "identical to `exception.stacktrace`"). Each one "must not be used on the Profile signal". — [OTel semconv registry: code](https://opentelemetry.io/docs/specs/semconv/registry/attributes/code/)
- Deprecated and replaced: `code.function` → `code.function.name` (now fully qualified), `code.filepath` → `code.file.path`, `code.lineno` → `code.line.number`, `code.column` → `code.column.number`, and `code.namespace` was folded into `code.function.name`. — [OTel semconv registry: code](https://opentelemetry.io/docs/specs/semconv/registry/attributes/code/)

**Span events are being deprecated (March 2026)**
- OTel announced that the tracing spec will deprecate `Span.AddEvent` and `Span.RecordException` in favour of log-based events ("logs with names") emitted through the Logs API and correlated with the active span context. New code is expected to write events as logs. — [OTel blog: Deprecating Span Events API](https://opentelemetry.io/blog/2026/deprecating-span-events/)
- Span events already in OTLP "remain valid" and views that show events on spans keep working. SDKs will offer a way to turn log-based events back into span events. Instrumentations may add opt-ins such as `OTEL_SEMCONV_EXCEPTION_SIGNAL_OPT_IN`. — [OTel blog](https://opentelemetry.io/blog/2026/deprecating-span-events/)
- Phased timeline with no calendar dates: current stable majors stay compatible → opt-in log-based events → SDKs make log events first-class and deprecate span-event methods → next major versions of instrumentations and semconv move events and exceptions to the Logs API. The full plan is in OTEP 4430. — [OTel blog](https://opentelemetry.io/blog/2026/deprecating-span-events/); [Datadog OTel news, Mar 2026](https://opensource.datadoghq.com/otel-news/2026/03/)

**SDK limits that matter for function- and branch-level capture**
- SDK defaults: `OTEL_SPAN_EVENT_COUNT_LIMIT` = 128, `OTEL_SPAN_ATTRIBUTE_COUNT_LIMIT` = 128, `OTEL_SPAN_LINK_COUNT_LIMIT` = 128, `OTEL_EVENT_ATTRIBUTE_COUNT_LIMIT` = 128, `OTEL_ATTRIBUTE_COUNT_LIMIT` = 128. `OTEL_ATTRIBUTE_VALUE_LENGTH_LIMIT` and `OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT` default to **no limit**. The default sampler is `parentbased_always_on`. — [OTel SDK environment variables](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/)

**Profiles signal**
- Profiles entered **public [ALPHA]** (blog dated 2026). It "should not be used for critical production workloads", and production-ready backends "have not yet emerged". It needs OTel Collector **v0.148.0+**. Profile samples can carry `trace_id`/`span_id` for correlation. Beta and GA are planned, with no timeline. — [OTel blog: Profiles enters public Alpha](https://opentelemetry.io/blog/2026/profiles-alpha)
- A vendor article updated in Aug 2026 says profiles are still under active development, that the wire format has already had breaking changes, and that traces, metrics and logs are the stable OTLP signals. — [Dash0 (secondary)](https://www.dash0.com/knowledge/what-is-continuous-profiling)
- A DEV Community post claims GA was targeted for Q3 2026. I found no confirmation on opentelemetry.io. — [DEV Community (unverified)](https://dev.to/x4nent/opentelemetry-profiles-public-alpha-ebpf-fourth-signal-collector-v01510-and-opamp-fleet-6g3)

**Existing function-level instrumentation**
- Java agent: `otel.instrumentation.methods.include` (env `OTEL_INSTRUMENTATION_METHODS_INCLUDE`) adds spans around listed methods with no code change, e.g. `com.example.MyClass[method1,method2]`. `@WithSpan` annotations are also available. — [OTel Explorer: Java methods instrumentation](https://explorer.opentelemetry.io/java-agent/instrumentation/methods); [OTel Java annotations](https://opentelemetry.io/docs/languages/java/annotations)
- Python zero-code instrumentation (`opentelemetry-instrument`, `opentelemetry-bootstrap`) monkey-patches *known libraries* (Flask, Django, requests, SQLAlchemy, etc.). My search found no equivalent for arbitrary user functions; manual spans or decorators are the usual route. — [opentelemetry-instrumentation on PyPI](https://pypi.org/project/opentelemetry-instrumentation/0.63b0/)
- `opentelemetry-instrumentation-fastapi` creates a server span per request plus internal spans for ASGI `receive`/`send` (droppable with `exclude_spans`). It supports `excluded_urls`, `server_request_hook`, `client_request_hook` and `client_response_hook`, and header capture via `OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_REQUEST/RESPONSE`, with `..._SANITIZE_FIELDS` replacing matches with `[REDACTED]` (these env-var names are "still experimental"). The docs mention no capture of request/response bodies and no function-level spans. — [opentelemetry-instrumentation-fastapi docs](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html)

**Correlation and export**
- W3C Trace Context Level 1 has been a **W3C Recommendation** since 23 Nov 2021. `traceparent` = `version-traceid-parentid-traceflags`, e.g. `00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01`. Only the `sampled` flag is defined. `tracestate` carries vendor-specific data, up to 32 members. — [W3C Trace Context](https://www.w3.org/TR/trace-context/)
- Datadog has a direct OTLP traces intake (no Agent or Collector needed) that accepts **HTTP/protobuf only** (no grpc or http/json), authenticated with a `dd-api-key` header, with a **3.2 MB request limit** (413 if exceeded). The trace-specific doc page labels it **[PREVIEW]** (access via CSM). Datadog's blog says direct OTLP intake is "generally available", so the sources conflict. For production, Datadog still recommends the Agent or a Collector with the Datadog exporter. — [Datadog OTLP traces intake](https://docs.datadoghq.com/opentelemetry/setup/agentless/traces); [Datadog blog](https://datadoghq.com/blog/native-otel-with-datadog)
- Honeycomb accepts OTLP at `https://api.honeycomb.io` (HTTP `/v1/traces`, or gRPC on `:443`; EU at `api.eu1.honeycomb.io`) with the `x-honeycomb-team` API-key header. `x-honeycomb-dataset` is needed only for Classic. — [Cloudflare docs: export to Honeycomb](https://developers.cloudflare.com/workers/observability/exporting-opentelemetry-data/honeycomb); [OneUptime guide (secondary)](https://oneuptime.com/blog/post/2026-02-06-otel-honeycomb-otlp-grpc/view)

### Inferences
- **Recommendation: one span per instrumented function call** (`SpanKind.INTERNAL`, name = qualified function name), with `code.function.name`, `code.file.path` and `code.line.number` (all STABLE), as a child of the framework's server span. When an exception occurs, record it with the stable `exception.*` attributes; `code.stacktrace` is defined as identical to `exception.stacktrace`. This gives a graph that Jaeger, Tempo, Datadog and Honeycomb render natively as a waterfall.
- **Do not put branch-level data in span events.** The API is being deprecated, and the default 128-events-per-span limit would silently truncate loops. Branch outcomes (if/else taken, loop iteration counts) should stay in EasyAPI's native format. For OTel export, emit either (a) a summarising attribute on the function span (e.g. `easyapi.branches_taken=["L42:true","L57:false"]` under a project namespace, capped), or (b) opt-in log-based events correlated to the span. Treat branch export as off by default because of cost and cardinality.
- **Arg/return values should not be exported to OTel by default.** OTel value-length limits default to unlimited, and Datadog rejects requests over 3.2 MB. Export at most type, shape, size and a redacted, truncated preview, behind an explicit opt-in.
- **Join existing traces**: when EasyAPI runs alongside an existing OTel SDK, it should use the current span context (`trace_id`/`span_id`) instead of starting new traces. When it runs standalone, it should read and propagate `traceparent`, so its node graph links to the same trace in the customer's APM. When a recording is replayed or re-run, use **span links** (not parent/child) to tie the new trace to the original.
- **Profiles**: do not build on it in 2026. Its status is ALPHA, the wire format is unstable, and `code.*` attributes are explicitly barred from it.
- **Gap that EasyAPI fills:** Java has config-driven method instrumentation and Python does not. A Python `include` list (module/function globs) that wraps functions with spans would add something real, and EasyAPI could ship it as an OTel-compatible instrumentation.
- Export path: in-process OTLP exporter (HTTP/protobuf, the format all four backends accept) → optionally the customer's OTel Collector, where the redaction processor (Section 2) acts as a second safety net.

### Gaps
- I did not confirm which semconv release first marked `code.*` stable. The registry page shows no version.
- I did not read OTEP 4430 directly.
- I found no source for Grafana Tempo's or Jaeger's OTLP receiver configuration (both are widely known to ingest OTLP natively, but that was not verified here).
- I did not confirm whether W3C Trace Context Level 2 has reached Recommendation.
- I found no published per-span cost figures from Datadog or Honeycomb for high-cardinality function spans.

---

## 2. Security and privacy of captured data: scrubbing approaches, secure-by-default, LGPD/GDPR, enterprise controls

### Takeaway
Every mature vendor scrubs in layers: a key/identifier denylist in the SDK before data leaves the process, configurable hooks, then server-side or pipeline redaction. None of them ships Brazilian identifiers (CPF/CNPJ) out of the box, so EasyAPI has to provide them. LGPD's necessity principle (Art. 6 III), security-by-design duty (Art. 46), retention/elimination rule (Art. 16) and incident regime (Art. 48 + ANPD Res. 15/2024) mean captured payloads should be minimised, redacted at capture time, encrypted, access-controlled and short-lived by default.

### Cited Findings
**Sentry**
- Server-side scrubbing is on by default. It scrubs values that look like credit cards (basic regex) and any value or key containing: `password, secret, passwd, api_key, apikey, auth, credentials, mysql_pwd, privatekey, private_key, token, bearer`. A matching key such as `credentials` can null an entire object. IP addresses are **not** scrubbed by default (separate setting). It offers "Additional Sensitive Fields", "Safe Fields" and Advanced Data Scrubbing rules. — [Sentry server-side scrubbing](https://docs.sentry.io/security-legal-pii/scrubbing/server-side-scrubbing/)
- Python SDK: the `before_send`, `before_send_transaction` and `before_send_span` hooks let you "scrub any data before it is sent". `EventScrubber` uses `DEFAULT_DENYLIST` (passwords, auth, sessions, cookies, CSRF) plus `DEFAULT_PII_DENYLIST` (e.g. IPs) when `send_default_pii` is False. It is **non-recursive by default** for performance (`EventScrubber(recursive=True)` to change). `send_default_pii` is being replaced by a finer-grained `data_collection` option and will be removed in SDK 3.0. Stack-local variables are collected and can be scrubbed or disabled. — [Sentry Python: sensitive data](https://docs.sentry.io/platforms/python/data-management/sensitive-data/)

**Datadog Dynamic Instrumentation (closest analogue: it captures variable values at runtime)**
- Three layers: identifier and type rules redact **in the customer's infrastructure before upload**, redaction modes control visibility, and Sensitive Data Scanner redacts after ingestion (it "doesn't replace the first layer"). — [Datadog DI sensitive data scrubbing](https://docs.datadoghq.com/dynamic_instrumentation/sensitive-data-scrubbing/)
- `DD_DYNAMIC_INSTRUMENTATION_REDACTED_IDENTIFIERS` adds names (e.g. `firstName,lastName,phoneNumber`) and `..._REDACTION_EXCLUDED_IDENTIFIERS` removes defaults. Redaction applies to method arguments, locals, class attributes and **dictionary keys**. `DD_DYNAMIC_INSTRUMENTATION_REDACTED_TYPES` redacts whole classes and **also forbids placing probes inside them**. Examples of default identifiers include `password` and `accessToken`; the full list is in the SDK source (`Redaction.java`). — [Datadog DI sensitive data scrubbing](https://docs.datadoghq.com/dynamic_instrumentation/sensitive-data-scrubbing/)

**OpenTelemetry Collector redaction processor**
- Stability: **traces [BETA]; logs and metrics [ALPHA]**. It is allowlist-based and **fails closed**: with an empty `allowed_keys`, all attributes are removed. Other options: `blocked_values` (regex masking), `allowed_values`, `blocked_key_patterns`, `ignored_keys`, `hash_function` (md5/sha1/sha3/hmac-sha256/hmac-sha512; md5/sha1 rejected in FIPS mode; HMAC recommended for low-entropy data such as IPs), `masking_string` (default `****`), a `summary` audit level (debug/info/silent), and `url_sanitizer` and `db_sanitizer` (SQL, Redis, MongoDB, etc.). Sample Visa regex: `4[0-9]{12}(?:[0-9]{3})?`. — [redactionprocessor README](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/processor/redactionprocessor/README.md)

**Microsoft Presidio (docs now at presidio.dataprivacystack.org)**
- Global recognizers: CREDIT_CARD (pattern + **checksum**), CRYPTO, DATE_TIME, EMAIL_ADDRESS, IBAN_CODE (checksum), IP_ADDRESS, MAC_ADDRESS, NRP, LOCATION, PERSON (NER), PHONE_NUMBER, MEDICAL_LICENSE, URL, UUID. Country packs cover the US, UK, Spain, Italy, Poland, Singapore, Australia, India, Finland, Korea, Nigeria, Philippines, Canada, Sweden, South Africa, Thailand, Turkey and Germany. **No Brazil recognizer: no CPF or CNPJ.** Custom recognizers are supported. — [Presidio supported entities](https://presidio.dataprivacystack.org/supported_entities/)

**LGPD (Lei 13.709/2018) and ANPD**
- Art. 5 I: personal data is any information about an identified or identifiable natural person. Art. 6 III (**necessidade**): processing is limited to the "mínimo necessário". Art. 6 VII (**segurança**). Art. 12: anonymised data is not personal data unless the anonymisation can be reversed with reasonable means. Art. 13 §4: defines pseudonymisation (re-linkable only with separately held information). Art. 16: data must be **eliminated after processing ends**, with exceptions such as legal obligation or anonymised use by the controller. Art. 37: controller and processor must keep a **record of processing operations**. Art. 46: technical and administrative security measures, to be observed "desde a concepção do produto ou serviço" (by design). Art. 48: notify the ANPD and data subjects of incidents that may cause relevant risk or harm. Art. 52: fines up to **2% of revenue, capped at R$ 50 million per infraction**. — [Lei 13.709/2018 (Planalto)](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm)
- ANPD Resolution CD/ANPD nº 15/2024 (incident communication regulation) requires controllers to keep an incident record for **at least 5 years**, including incidents not reported to the ANPD. — [Lefosse client alert](https://lefosse.com/noticias/alerta/client-alert-anpd-aprova-regulamento-de-comunicacao-de-incidente-de-seguranca/); [Machado Meyer](https://www.machadomeyer.com.br/pt/inteligencia-juridica/publicacoes-ij/direito-digital/anpd-publica-regulamento-de-comunicacao-de-incidente-de-seguranca)
- The notification deadline is reported as three (business) days. — [Contábeis](https://www.contabeis.com.br/noticias/55651/anpd-vazamento-de-dados-deve-ser-comunicado-em-ate-tres-dias/) (secondary; check the final text of Res. 15/2024)

### Inferences
- **Secure-by-default design for EasyAPI, built from the patterns above:**
  1. **Capture-time redaction in the process**, as Datadog DI and Sentry `before_send` do. Nothing unredacted reaches disk or the network. Default key denylist: the union of Sentry's list (password, secret, passwd, api_key, apikey, auth, credentials, mysql_pwd, privatekey, private_key, token, bearer) and Datadog's examples (accessToken), plus session, cookie, csrf, authorization, set-cookie, client_secret, refresh_token and jwt. Add Brazilian keys: `cpf`, `cnpj`, `rg`, `senha`, `token`, `chave`, `cartao`, `pis`, `nis`, `cns`, `titulo_eleitor`.
  2. **Value-pattern detectors with checksums**: credit card (Luhn), **CPF and CNPJ with check-digit validation** (missing from Presidio, so EasyAPI should ship them, ideally also as Presidio custom recognizers so enterprises can reuse them), email, phone (+55), IP, JWT (`eyJ...`), and AWS/GCP/GitHub-style token prefixes.
  3. **Type-level redaction**: user-declared types such as `SecretStr` or ORM `User` models are never serialised, mirroring `DD_..._REDACTED_TYPES`. Pydantic `SecretStr` should be redacted automatically.
  4. **Recursive scrubbing on by default.** Sentry's non-recursive default trades safety for speed, which suits an error tracker but not a tool whose purpose is capturing nested payloads.
  5. **Bounded capture**: max depth, max collection items and max string length, so huge payloads never get stored. Store a shape summary (type, length) instead of the value when limits are hit.
  6. **Modes**: `off` (structure only: function, timing, branch, exception type), `redacted` (default), and `full` (explicit opt-in, dev/local only, with a warning banner in the UI).
  7. **HMAC instead of plain hashing** for values that must stay correlatable. Low-entropy data such as CPF (11 digits) is trivially brute-forced if hashed with SHA without a key; the Collector README makes the same point for IPs.
  8. **Defence in depth on export**: document a reference OTel Collector config with the redaction processor (traces = BETA), `allowed_keys` limited to the EasyAPI/code.* schema, so it fails closed.
- **LGPD mapping:** Art. 6 III and Art. 46 support redaction and minimisation by default. Art. 16 supports **short default retention** (e.g. 7 days for local dev, configurable) with automatic purge. Art. 12/13 mean HMAC-pseudonymised data is still personal data, because it can be re-linked with the key; only irreversible removal counts as anonymisation. Art. 37 and Res. 15/2024 support **audit logs** of who viewed which trace and of export events. Recorded payloads from production in energy or government systems would make EasyAPI's store a database of personal data in its own right.
- **Enterprise controls expected** (inferred; no sector-specific source found): encryption at rest (e.g. SQLCipher or filesystem-level), TLS for the UI, SSO/OIDC plus RBAC (who can see raw values versus redacted ones), immutable audit log, configurable retention, and a **fully offline/air-gapped mode**: no CDN assets, no telemetry phone-home, and all assets inside the wheel (see Section 4).
- GDPR equivalents (Art. 5(1)(c) minimisation, Art. 25 by design, Art. 32 security, Art. 33 72-hour breach notice) map one-to-one with the LGPD articles above. They were not fetched in this session.

### Gaps
- I did not obtain the full default identifier list in Datadog's `Redaction.java`, Datadog DI capture limits (depth, collection size, string length), or Sensitive Data Scanner rule details.
- I could not confirm from the fetched page Sentry's Advanced Data Scrubbing methods (mask/hash/replace) or the exact `DEFAULT_DENYLIST` contents.
- ANPD has no specific rule on retention of application or debug logs. LGPD sets no fixed log-retention period; the Marco Civil da Internet (arts. 13–15) retention duties come from background knowledge and were not verified.
- I found no authoritative source on Brazilian energy-sector or government requirements (e.g. GSI/PR normative instructions, ANEEL cyber rules, data-residency/"nuvem de governo") for on-prem or air-gapped tools. This needs targeted follow-up.
- Did not fetch the final text of ANPD Res. 15/2024 to confirm the "3 dias úteis" deadline.

---

## 3. License and governance: MIT vs Apache-2.0 vs AGPL vs FSL/BSL vs Commons Clause; precedents; governance hygiene

### Takeaway
For a dev tool that needs both enterprise procurement approval and grassroots adoption, **Apache-2.0** is the strongest default: permissive, with an explicit patent grant, required for CNCF, and the same license as OpenTelemetry's ecosystem. Precedents show that use restrictions (n8n's Sustainable Use License, AppMap's Commons Clause, Sentry's FSL) are not OSI open source and come with marketing and procurement trade-offs. AGPL (Grafana) stays OSI-approved but sits on many corporate "do not use" lists. Governance hygiene now has machine-checked standards: OpenSSF Scorecard checks, SECURITY.md, SBOM, and Sigstore-signed PyPI attestations (PEP 740).

### Cited Findings
**License mechanics**
- choosealicense.com: **MIT** permits commercial use, distribution, modification and private use, with no "Patent use" permission listed. **Apache-2.0** adds **"Patent use"** and requires "State changes". **AGPL-3.0** adds the conditions "Disclose source", "Same license" and **"Network use is distribution"**. **MPL-2.0** is weak copyleft at file level. — [choosealicense.com/licenses](https://choosealicense.com/licenses/)
- The CNCF requires projects to use **Apache-2.0** or a license on the CNCF allowlist; applicants must confirm this before applying for Sandbox. — [CNCF project lifecycle](https://contribute.cncf.io/projects/lifecycle/)

**Precedents**
- **n8n**: the Sustainable Use License (fair-code, created by n8n in **2022**) covers most of the repo. Files with `.ee.` in the name fall under the n8n Enterprise License, and those features need a license key. n8n moved *from* Apache-2.0 + Commons Clause *to* the SUL. n8n says it does not call itself open source, because OSI licenses can't restrict use. — [n8n docs: Sustainable Use License](https://docs.n8n.io/sustainable-use-license/); [n8n docs: fair-code](https://docs.n8n.io/faircode-license)
- A competitor (Activepieces) characterises the SUL as allowing internal business use but not reselling, embedding, or hosting n8n for others. — [Activepieces blog (competitor, biased)](https://www.activepieces.com/blog/n8n-license-fair-code-community-enterprise-2026)
- **AppMap**: the npm package `@appland/appmap` (v3.206.0) declares its license as **"Commons Clause + MIT"**. — [npm registry metadata](https://registry.npmjs.org/@appland/appmap/latest)
- **Sentry**: introduced the **Functional Source License (FSL)** in late 2023 (a non-compete that converts to **Apache-2.0 or MIT after two years**) and launched the "Fair Source" category in 2024. Sentry reports 10,000+ orgs self-hosting under FSL, 100k+ cloud customers and $100M ARR (Sentry's own claims). Critics say fair source is not open source. — [Sentry: now Fair Source](https://blog.sentry.io/sentry-is-now-fair-source); [InfoQ on FSL](https://www.infoq.com/news/2023/12/functional-source-license); [TechCrunch 2024](https://techcrunch.com/2024/09/22/some-startups-are-going-fair-source-to-avoid-the-pitfalls-of-open-source-licensing/); [open.sentry.io/licensing](https://open.sentry.io/licensing)
- **Grafana Labs**: in April 2021 moved Grafana, Loki and Tempo from Apache-2.0 to **AGPLv3**. Plugins, agents and some libraries stayed Apache-2.0, and AGPL was chosen over SSPL. CEO Raj Dutt acknowledged that AGPL may create "red tape" for internal use at many companies. Commentators noted that AGPL is often on large tech firms' do-not-use lists (Google bans AGPL). — [Grafana relicensing blog](https://grafana.com/blog/2021/04/20/grafana-loki-tempo-relicensing-to-agplv3); [Q&A with CEO](https://grafana.com/blog/2021/04/20/qa-with-our-ceo-on-relicensing/); [DevClass](https://devclass.com/2021/04/21/all-change-grafana-switches-core-open-source-projects-from-apache-to-agplv3-licensing/)

**Contribution agreements**
- A **DCO** is a lightweight sign-off (`git commit -s`) with Git history as the record. A **CLA** is a legal agreement that grants broader rights, including a patent license, and can let the project relicense later. — [Linux Foundation best practices: CLAs](https://bestpractices.linuxfoundation.org/ip/contribution-mechanisms-cla.html); [opensource.com CLA vs DCO](https://opensource.com/article/18/3/cla-vs-dco-whats-difference)
- CERN's OSPO recommends the DCO. The LF's EasyCLA blocks merges until a CLA is signed. — [CERN OSPO](https://ospo.docs.cern.ch/recommendations/CLAs-and-DCOs); [OpenColorIO/ASWF](https://opencolorio.readthedocs.io/en/main/aswf/cla_dco.html)

**CNCF Sandbox**
- You apply by opening an issue with the application form in the `cncf/sandbox` repo. Applications are reviewed roughly first-in-first-out, and the old sponsor/SIG requirement was replaced by a simple TOC vote. Sandbox is the entry level and requires **no due diligence**. — [cncf/sandbox](https://github.com/cncf/sandbox); [CNCF lifecycle](https://contribute.cncf.io/projects/lifecycle/)

**Supply-chain and security hygiene**
- OpenSSF Scorecard has 20 checks: Binary-Artifacts, Branch-Protection, CI-Tests, CII-Best-Practices, Code-Review, Contributors, Dangerous-Workflow, Dependency-Update-Tool, Fuzzing, License, Maintained, Packaging, Pinned-Dependencies, SAST, SBOM, Security-Policy, Signed-Releases, Token-Permissions, Vulnerabilities, Webhooks. — [Scorecard checks.md](https://github.com/ossf/scorecard/blob/main/docs/checks.md)
- **Signed-Releases** looks for `.minisig/.asc/.sig/.sign/.sigstore/.sigstore.json/.intoto.jsonl` on GitHub release assets: signatures score 8/10, SLSA provenance (`.intoto.jsonl`) 10/10. **SBOM** gives 5/10 for any SBOM and +5 when it is published as a release artifact. **Security-Policy** gives 6/10 for a contact email or link in SECURITY.md, plus points for disclosure-timeline text. — [Scorecard checks.md](https://github.com/ossf/scorecard/blob/main/docs/checks.md)
- **PEP 740** (resolved 17 Jul 2024): PyPI stores Sigstore-signed in-toto attestations tied to **Trusted Publishing** identities. The PyPA GitHub publish action generates them **by default** with trusted publishing; `uv publish` alone does not. Sigstore describes PyPI attestations as **GA**. — [PEP 740](https://peps.python.org/pep-0740); [PyPI attestations docs](https://docs.pypi.org/attestations/); [Sigstore blog](https://blog.sigstore.dev/pypi-attestations-ga/)

### Inferences
- **Recommendation: Apache-2.0 for everything** (Python agent, UI, exporters). It is permissive enough for small projects and Brazilian public bodies, has an explicit patent grant that enterprise legal teams look for (MIT has none), and is CNCF-compatible, which keeps a future OTel-adjacent or CNCF path open.
- **Avoid Commons Clause, SUL and FSL for the core.** These licenses work for a vendor monetising a hosted product (n8n, Sentry), but they are not OSI-approved. Many enterprises and Brazilian public procurement policies screen for OSI licenses, and every non-OSI license triggers a legal review. A commercial layer, if ever needed, can follow an open-core split (separate repo or directory for enterprise SSO/RBAC/audit) without contaminating the Apache core.
- **Avoid AGPL for the agent.** The agent runs inside customers' application processes, so AGPL's "network use is distribution" is a real legal question for anyone running it inside a web API, which is exactly the "red tape" Grafana's CEO described.
- **Use a DCO, not a CLA.** It means less friction for community contributors. Apache-2.0 §5 already licenses inbound contributions under the same terms, patent grant included. Adopt a CLA only if relicensing flexibility becomes a business requirement, which itself signals that a license change may come, something the community tends to read as a negative.
- **Governance checklist for day one:** SECURITY.md with a private reporting channel (GitHub private vulnerability reporting) and a disclosure timeline; CODE_OF_CONDUCT; GOVERNANCE.md and MAINTAINERS; branch protection with required review and status checks; Dependabot or Renovate; CodeQL (SAST); pinned GitHub Actions; least-privilege workflow tokens; PyPI Trusted Publishing with PEP 740 attestations; a CycloneDX or SPDX SBOM attached to each GitHub release; Sigstore bundles and SLSA provenance on release assets (Scorecard 10/10 for Signed-Releases); an OpenSSF Best Practices badge; and a Scorecard GitHub Action publishing the score. These are the artifacts that energy and government security reviews ask for.

### Gaps
- I did not fetch OpenTelemetry's own LICENSE or CLA policy (OTel is Apache-2.0 as a CNCF project, and I believe it uses the CNCF CLA via EasyCLA, but this was not verified in this session).
- I did not verify AppMap's language agents (appmap-python, appmap-java), which I believe are MIT; only the npm `@appland/appmap` package was checked. I found no data on adoption consequences of AppMap's Commons Clause.
- I found no quantitative data on n8n's adoption impact from the SUL, beyond the fact that n8n is widely used.
- I found no current (2025–26) list of CNCF sandbox evaluation criteria. The `process/sandbox.md` URL returned 404.
- Brazilian public-sector software licensing policy (e.g. Portal do Software Público Brasileiro rules) was not researched.

---

## 4. UI stack for large interactive node graphs: libraries, layout, performance, n8n patterns, shipping the UI

### Takeaway
**React Flow (`@xyflow/react`, MIT)** is the default choice. It is the most used node-graph library, MIT "forever", and Pro sells examples and support rather than features. **Svelte Flow 1.x** (May 2025) and **Vue Flow** (MIT, used by n8n's canvas) are close siblings. Pair it with **ELK.js** (layered algorithm with ports and compound/nested nodes, run in a Web Worker) for automatic layout. `@dagrejs/dagre` is a lighter fallback; n8n itself uses it. Use collapse/hide for subflows, because no library publishes a hard node limit and DOM-based canvases degrade with many visible nodes. Ship the built UI inside the Python wheel and serve it locally with no CDN, which FastAPI's own docs show is needed for offline use.

### Cited Findings
**React Flow / xyflow**
- React Flow "is open-source MIT-licensed software, and it will be forever". Pro subscriptions (Starter $169/mo, Professional $289/mo, Enterprise custom) buy Pro Examples, templates, prioritized issues, team seats and support. No core features are gated. — [reactflow.dev/pro](https://reactflow.dev/pro)
- Performance guidance: memoize custom nodes and edges (`React.memo`), `useCallback`/`useMemo` for props, and avoid subscribing components to the whole `nodes`/`edges` arrays. For big nested trees, **toggle `hidden` to collapse and expand**, and simplify CSS (no shadows or animations). **No node-count limits or benchmarks are published.** — [React Flow performance](https://reactflow.dev/learn/advanced-use/performance)
- Svelte Flow **1.0** was released 2025-05-14 (Svelte 5; reconnectable edges, keyboard navigation, accessibility), and 1.4.0 followed on 2025-10-20. React Flow 12 was released July 2024. — [Svelte Flow 1.0](https://svelteflow.dev/whats-new/2025-05-14); [Svelte Flow 1.4](https://svelteflow.dev/whats-new/2025-10-20)

**Vue Flow and n8n**
- Vue Flow is MIT, by Burak Cakmakoglu, and derives from React Flow's code. `@vue-flow/core` is at v1.48.x. — [Vue Flow guide](https://vueflow.dev/guide/); [jsDelivr @vue-flow/core](https://www.jsdelivr.com/package/npm/@vue-flow/core)
- n8n's editor-ui `package.json` lists `@vue-flow/core` 1.48.0, `@vue-flow/background`, `@vue-flow/controls`, **`@vue-flow/minimap`** and `@vue-flow/node-resizer`, plus **`@dagrejs/dagre` ^1.1.4** (no elkjs). — [n8n editor-ui package.json](https://github.com/n8n-io/n8n/blob/master/packages/frontend/editor-ui/package.json)
- n8n's new canvas went Alpha → **Beta and default for new users in v1.70.0**, with smoother editing of "hundreds of nodes". Workflows with large in-memory execution data can still slow the editor. — [n8n community: new canvas beta](https://community.n8n.io/t/help-us-test-the-new-n8n-canvas-beta/60070). An older (pre-new-canvas) thread reported the UI as "very slow with more than 100 nodes". — [n8n community](https://community.n8n.io/t/ui-very-slow-with-more-than-100-nodes/8236)
- n8n per-node execution data: the OUTPUT panel switches between **Table and JSON** views. **Pin data** freezes a node's output for development; pinned data is editable as JSON and can be pasted from past executions. Pinning is not available for production executions, not with binary data, and not on multi-output nodes. — [n8n data pinning](https://docs.n8n.io/data/data-pinning/)
- n8n nodes run **once per input item** by default. Loops are built by wiring an output back (with IF) or with Loop Over Items (batch size). "Execute Once" processes only the first item. — [n8n looping](https://docs.n8n.io/flow-logic/looping/)

**Other graph libraries**
- **JointJS** core is **MPL-2.0**. **JointJS+** is commercial and adds features such as virtual rendering for many objects (that second claim comes from a vendor-adjacent blog). — [JointJS license](https://www.jointjs.com/license); [Neoteric blog](https://neoteric.eu/blog/how-to-choose-jointjs-vs-jointjsplus/)
- **Sigma.js** (MIT) v2 is a WebGL renderer built for large graphs (thousands of nodes and edges). It is suited to network exploration, not port-based flow diagrams. — [Sciences Po médialab: Sigma.js v2](https://medialab.sciences-po.fr/actu/sigmajs-version-2-finally-released)
- **Cytoscape.js** (MIT) added a **WebGL renderer preview in v3.31** for large networks; canvas remains fine for small and medium graphs. — [Cytoscape.js blog: WebGL preview](https://blog.js.cytoscape.org/2025/01/13/webgl-preview/)

**Layout engines**
- **ELK Layered** supports **ports** and **compound (hierarchical) graphs**, including edges that cross hierarchy levels. It runs in five phases: cycle breaking, layering, crossing minimization, node placement, edge routing. — [ELK Layered reference](https://eclipse.dev/elk/reference/algorithms/org-eclipse-elk-layered.html); [ELK blog 2025: Layered overview](https://eclipse.dev/elk/blog/posts/2025/25-08-21-layered.html)
- **elkjs** runs in a **Web Worker** (it falls back to the main thread if the worker isn't available). A slim `elkjs/lib/elk-api` plus `workerFactory` pattern is used with React Flow. — [Stately: React Flow + ELK pipeline](https://prod.stately.ai/docs/packages/graph/react-flow-elk-pipeline)
- **dagre**: per the README, only the DagreJS-org package (`@dagrejs/dagre`) receives updates. The repo is not archived. Snyk rates its maintenance as "Sustainable", though one Snyk snapshot reported no release in 12 months, so the sources are inconsistent. dagre is the default layout for D2 and Mermaid flowcharts. — [dagrejs/dagre](https://github.com/dagrejs/dagre); [Snyk advisor](https://snyk.io/advisor/npm-package/dagre); [D2 docs](https://d2lang.com/tour/dagre/)
- **Graphviz WASM**: `@hpcc-js/wasm-graphviz` (v3 monorepo split) runs in the browser and Node. `Graphviz.load()` then `.dot()` returns SVG and supports dot, neato, twopi and other engines. — [hpcc-js-wasm graphviz README](https://hpcc-systems.github.io/hpcc-js-wasm/packages/graphviz/README.html)

**Shipping the UI with Python**
- FastAPI loads Swagger UI and ReDoc **from a CDN by default** (jsDelivr: `swagger-ui-dist@5`, `redoc@2`). For offline use you must set `docs_url=None`, download the assets, mount `StaticFiles`, and pass `swagger_js_url` and similar options to `get_swagger_ui_html`. — [FastAPI: custom docs UI assets](https://fastapi.tiangolo.com/how-to/custom-docs-ui-assets/)
- `dagster-webserver` 1.13.6 ships a universal `py3-none-any` wheel of **~12.1 MB** (sdist ~11.9 MB) and serves the UI's static assets itself. The wheel size suggests the compiled UI is bundled, but that is not confirmed. — [PyPI dagster-webserver 1.13.6](https://pypi.org/project/dagster-webserver/1.13.6/)

### Inferences
- **Recommended stack:** React + `@xyflow/react` (MIT) + `elkjs` in a Web Worker (layered, `elk.direction=RIGHT`, ports for argument and return handles, `hierarchyHandling=INCLUDE_CHILDREN` for nested subflows). Keep `@dagrejs/dagre` as a fast fallback for very large flat graphs. Svelte Flow is a reasonable alternative if bundle size matters. Vue Flow fits only if the team prefers Vue; it is n8n's choice and also MIT. Avoid JointJS for the core, because MPL-2.0 is weak copyleft and the scale features are in commercial JointJS+. Sigma.js and Cytoscape.js (WebGL) suit an optional "overview" mode for call graphs with thousands of nodes, not the main node-and-port editor view.
- **Scaling strategy (inferred from the React Flow guidance and n8n's experience):** default to a **collapsed view**, one node per top-level function or module group, and expand on click (React Flow `parentId` subflows plus the `hidden` toggle). Aggregate loop iterations into a single node with an **iteration selector**, the counterpart to n8n's per-run view, rather than one node per iteration. Lazy-load argument and return payloads on node selection instead of putting them in node data, since n8n's experience shows large in-memory execution data slows the canvas. Include the minimap (`@xyflow/react` MiniMap; n8n uses `@vue-flow/minimap`), search that focuses and highlights a node by function name, file or exception, and a "path taken" highlight for branches.
- **n8n-like per-node inspector:** a side panel with Input (args) / Output (return or exception) tabs offering **Table / JSON / Schema** views, a run/iteration selector for nodes invoked multiple times, and a "copy as fixture" action (similar to pinning) that exports the captured input as a pytest fixture or replay payload.
- **Shipping:** build the SPA in CI (Vite) and include `dist/` as package data in the wheel (as Dagster does), serve it from a Starlette/FastAPI sub-app (`/_easyapi`), and **load nothing from a CDN**. That is required for air-gapped energy and government sites, and FastAPI's default CDN behaviour is the cautionary example. Also offer a **standalone viewer**: `easyapi view trace.jsonl` launches a local server, and/or a single-file HTML export with inlined JS so a trace can be attached to a ticket and opened offline. Pin the frontend lockfile and include the JS dependencies in the SBOM.

### Gaps
- No published, reproducible node-count benchmarks for React Flow, Vue Flow or Svelte Flow (the docs give none). A local benchmark is recommended, roughly 500 / 2,000 / 5,000 nodes with custom nodes.
- I did not research Rete.js, LiteGraph (litegraph.js / ComfyUI fork), AntV G6 (v5) licensing and performance, or d3-dag maintenance.
- I did not confirm which React Flow examples (auto-layout, sub-flows, helper lines) are Pro-only.
- I did not confirm whether n8n's UI has an explicit "Run N of M" selector; the looping page does not describe it.
- I did not verify the contents of MLflow's or Prefect's wheels (bundled UI). Dagster's is inferred from wheel size.

---

## 5. Storage of traces: local SQLite/DuckDB vs JSONL vs OTLP backend; retention and size

### Takeaway
I found no authoritative sources in this session that compare local storage engines for this use case. The recommendation below is inference, constrained by the facts collected above (OTel limits, Datadog's 3.2 MB OTLP request limit, LGPD retention and security duties).

### Cited Findings
- Datadog's OTLP traces intake rejects requests over **3.2 MB**, which bounds how much captured payload can travel per export batch to that backend. — [Datadog OTLP traces intake](https://docs.datadoghq.com/opentelemetry/setup/agentless/traces)
- OTel SDKs cap spans at 128 events and 128 attributes by default, with **no default limit on attribute value length**. — [OTel SDK environment variables](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/)
- LGPD Art. 16 requires elimination after processing ends, and Art. 46 requires security measures by design. — [Lei 13.709/2018](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm)

### Inferences
- **Recommended tiering:**
  1. **Default (small projects, dev): an embedded SQLite file** (in the Python stdlib, so zero dependencies) with one row per request and per call node; payloads go in a separate table as compressed JSON blobs that load lazily in the UI. Use WAL mode for concurrent writer and reader. Add TTL purge (e.g. 7 days or N MB cap) and optional encryption at rest (SQLCipher or the OS disk). SQLite is the natural fit for the "single-user local UI" case.
  2. **Interchange/portable: JSONL (one trace per line) or OTLP-JSON files** for sharing, CI artifacts and the standalone viewer. These are easy to attach, diff and redact again.
  3. **Analytics (optional): DuckDB**, querying the JSONL or Parquet exports for aggregate questions ("which branch is taken most?", "p95 by function"). Use it as an add-on reader, not the primary store, because DuckDB prefers a single writer process.
  4. **Enterprise: OTLP export** to the customer's existing backend (Tempo, Jaeger, Datadog, Honeycomb), sending structure (spans, code.*, timings, exception types) with payloads redacted or omitted. Keep the full redacted payloads only in EasyAPI's own store, under its retention and RBAC.
- **Size budgeting (rough estimate, not sourced):** with default caps (e.g. 1 KB preview per arg/return, depth 3, 50 items), a request touching about 200 instrumented functions would be on the order of a few hundred KB uncompressed per trace, so sampling (e.g. record 1% of production requests, 100% of errors, all in dev) and per-trace size caps are essential. Real numbers must come from benchmarks on the target apps.
- Write a summary row (route, status, duration, exception, trace_id) on every request even when payload capture is sampled out, so the trace list stays complete while sensitive data volume stays small. This is the necessity principle, LGPD Art. 6 III, applied in practice.

### Gaps
- I found no benchmarks or published per-trace size figures for function-level capture tools (e.g. AppMap, Sentry Python local-variable capture, Datadog DI snapshots).
- I did not research SQLite vs DuckDB concurrency or performance trade-offs for write-heavy tracing, or Parquet/Arrow export patterns, from primary sources.
- I did not check how comparable tools (AppMap's `.appmap.json` files, Sentry Spotlight, Logfire's local mode) store data locally.
