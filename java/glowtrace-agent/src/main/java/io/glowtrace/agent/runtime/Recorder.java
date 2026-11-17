package io.glowtrace.agent.runtime;

import io.glowtrace.agent.analysis.Registry;

import java.lang.annotation.Annotation;
import java.lang.reflect.Method;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Per-request execution recorder (thread-confined: Spring MVC is thread-per-request). */
final class Recorder {
    static final int MAX_FRAMES = 3000;
    static final int MAX_PATH = 4000; // node visits kept per frame
    static final int MAX_RAISED = 20;
    private static final SecureRandom RND = new SecureRandom();

    final String id = hex(8);
    final long t0 = System.nanoTime();
    final double startedAt = System.currentTimeMillis() / 1000.0;
    final List<FrameRec> frames = new ArrayList<>();
    final ArrayDeque<FrameRec> stack = new ArrayDeque<>();
    boolean truncated;
    boolean closed;
    int busy; // >0 while Glowtrace itself runs (capture...): ignore nested events
    String method;
    String uri;
    String traceId;

    static String hex(int bytes) {
        byte[] b = new byte[bytes];
        RND.nextBytes(b);
        StringBuilder sb = new StringBuilder(bytes * 2);
        for (byte x : b) sb.append(Character.forDigit((x >> 4) & 0xF, 16)).append(Character.forDigit(x & 0xF, 16));
        return sb.toString();
    }

    long now() {
        return (System.nanoTime() - t0) / 1000;
    }

    // ------------------------------------------------------------------ events

    FrameRec enter(MethodTable.MethodInfo mi, Object[] args) {
        if (closed) return null;
        MethodTable.FnRuntime fr = mi.runtime();
        if (fr == null) return null;
        if (frames.size() >= MAX_FRAMES) {
            truncated = true;
            return null;
        }
        FrameRec parent = stack.peekFirst();
        if (parent != null && parent.fr.middleware && !parent.fr.callsDirectly(parent.curLine, fr.fnId)) {
            parent = null; // reached through chain.doFilter(...): request-level frame, like the endpoint in Python
        }
        FrameRec f = new FrameRec(this, frames.size(), parent, fr, mi, now());
        try {
            f.args = Capture.captureNamed(fr.params, args);
        } catch (Throwable t) {
            f.args = new LinkedHashMap<>();
        }
        frames.add(f);
        stack.push(f);
        return f;
    }

    void exit(FrameRec f, Object ret, Throwable t) {
        if (stack.contains(f)) {
            while (!stack.isEmpty()) {
                if (stack.pop() == f) break;
            }
        }
        f.end = now();
        if (t != null) {
            f.exc = exception(t, f.curLine);
        } else {
            f.ret = Capture.capture(ret);
        }
    }

    void line(int mid, int line) {
        FrameRec top = stack.peekFirst();
        if (top == null) return;
        if (top.mi.id != mid && !lambdaOf(mid, top)) return;
        top.curLine = line;
        int node = top.fr.node(line);
        if (node < 0 || node == top.last) return;
        top.last = node;
        if (top.path.size() >= MAX_PATH) {
            top.truncated = true;
            if (top.overflow == null) top.overflow = new HashMap<>();
            top.overflow.merge(node, 1, Integer::sum);
            return;
        }
        top.path.add(new long[] {node, now()});
    }

    void thrown(Throwable t, int mid) {
        FrameRec top = stack.peekFirst();
        if (top == null || t == null) return;
        if (top.mi.id != mid && !lambdaOf(mid, top)) return;
        if (top.raised == null) top.raised = new ArrayList<>();
        if (top.raised.size() >= MAX_RAISED) return;
        Map<String, Object> r = new LinkedHashMap<>();
        r.put("line", top.curLine);
        r.put("type", t.getClass().getSimpleName());
        String msg = Capture.scrubText(message(t));
        r.put("message", msg.length() > 200 ? msg.substring(0, 200) : msg);
        top.raised.add(r);
    }

    /** Line events of lambda$host$N bodies are attributed to the enclosing method's frame. */
    private static boolean lambdaOf(int mid, FrameRec top) {
        MethodTable.MethodInfo li = MethodTable.byId(mid);
        return li != null && li.lambda && li.lambdaHost != null && li.lambdaHost.equals(top.mi.name)
                && li.type.equals(top.mi.type);
    }

    // ------------------------------------------------------------------ exceptions

    static String message(Throwable t) {
        try {
            String m = t.getMessage();
            return m == null ? "" : m;
        } catch (Throwable e) {
            return t.getClass().getSimpleName();
        }
    }

    static Map<String, Object> exception(Throwable t, int line) {
        Map<String, Object> e = new LinkedHashMap<>();
        e.put("type", t.getClass().getSimpleName());
        String msg = Capture.scrubText(message(t));
        e.put("message", msg.length() > 1000 ? msg.substring(0, 1000) + "…" : msg);
        e.put("line", line);
        String detail = detail(t);
        if (detail != null) e.put("detail", Capture.scrubText(detail));
        Integer st = statusCode(t);
        if (st != null) e.put("status_code", st);
        return e;
    }

    private static boolean extendsName(Class<?> c, String name) {
        for (Class<?> x = c; x != null; x = x.getSuperclass()) {
            if (x.getName().equals(name)) return true;
            for (Class<?> i : x.getInterfaces()) if (i.getName().equals(name)) return true;
        }
        return false;
    }

    private static String detail(Throwable t) {
        if (!extendsName(t.getClass(), "org.springframework.web.server.ResponseStatusException")) return null;
        try {
            Object r = t.getClass().getMethod("getReason").invoke(t);
            return r == null ? null : r.toString();
        } catch (Throwable e) {
            return null;
        }
    }

    /** HTTP status carried by well-known framework exceptions (@ResponseStatus, ErrorResponse). */
    static Integer statusCode(Throwable t) {
        try {
            if (extendsName(t.getClass(), "org.springframework.web.ErrorResponse")
                    || extendsName(t.getClass(), "org.springframework.web.server.ResponseStatusException")) {
                Object sc = t.getClass().getMethod("getStatusCode").invoke(t);
                Object v = sc.getClass().getMethod("value").invoke(sc);
                if (v instanceof Integer) return (Integer) v;
            }
            for (Class<?> x = t.getClass(); x != null && x != Throwable.class; x = x.getSuperclass()) {
                for (Annotation a : x.getDeclaredAnnotations()) {
                    if (!a.annotationType().getName().equals("org.springframework.web.bind.annotation.ResponseStatus")) {
                        continue;
                    }
                    for (String attr : new String[] {"code", "value"}) {
                        Object hs = a.annotationType().getMethod(attr).invoke(a);
                        Method vm = hs.getClass().getMethod("value");
                        Object v = vm.invoke(hs);
                        if (v instanceof Integer && (Integer) v != 500) return (Integer) v;
                    }
                    return 500;
                }
            }
        } catch (Throwable ignored) {
            // no status
        }
        return null;
    }

    // ------------------------------------------------------------------ result

    private static final String URI_VARS = "org.springframework.web.servlet.HandlerMapping.uriTemplateVariables";
    private static final String BEST_PATTERN = "org.springframework.web.servlet.HandlerMapping.bestMatchingPattern";

    Map<String, Object> toExecution(ServletBridge.Api api, Object req, Object resp, Throwable thrown) {
        long durUs = now();
        List<Map<String, Object>> fj = new ArrayList<>(frames.size());
        Map<Integer, FrameRec> byId = new HashMap<>();
        for (FrameRec f : frames) {
            fj.add(f.toJson());
            byId.put(f.id, f);
        }
        for (FrameRec f : frames) {
            if (f.parent != null) {
                FrameRec p = byId.get(f.parent);
                if (p != null) Store.INSTANCE.observe(p.fr.fnId, f.fr.fnId);
            }
        }
        String ctx = api.contextPath(req);
        String path = uri;
        String rel = path != null && !ctx.isEmpty() && path.startsWith(ctx) ? path.substring(ctx.length()) : path;
        if (rel != null && rel.isEmpty()) rel = "/";
        Object best = api.attribute(req, BEST_PATTERN);
        Registry reg = Registry.get();
        String routeId = reg == null ? null : reg.matchRoute(method, best == null ? null : best.toString(), rel);

        int status = api.status(resp);
        Map<String, Object> err = null;
        if (thrown != null) {
            Throwable root = unwrap(thrown);
            err = new LinkedHashMap<>();
            err.put("type", root.getClass().getSimpleName());
            String m = Capture.scrubText(message(root));
            err.put("message", m.length() > 500 ? m.substring(0, 500) : m);
            err.put("escaped", true);
            if (status < 400) status = 500;
        } else {
            // request-level frames: roots, or frames called (through the framework) by a user filter
            java.util.Set<String> mw = reg == null ? java.util.Set.of() : reg.middlewareFns();
            Map<String, Object> top = null;
            for (int i = 0; i < fj.size(); i++) {
                Map<String, Object> f = fj.get(i);
                if (f.get("exception") == null) continue;
                Integer parent = frames.get(i).parent;
                boolean boundary = parent == null || mw.contains(byId.get(parent).fr.fnId);
                if (boundary) top = f;
            }
            if (top != null) {
                @SuppressWarnings("unchecked")
                Map<String, Object> e = (Map<String, Object>) top.get("exception");
                err = new LinkedHashMap<>();
                err.put("type", e.get("type"));
                err.put("message", e.get("message"));
                err.put("escaped", false);
                if (e.get("status_code") != null) err.put("status_code", e.get("status_code"));
            }
        }
        Integer origin = errorOrigin(fj);
        if (err != null && origin != null) err.put("frame", origin);

        Map<String, Object> request = new LinkedHashMap<>();
        request.put("headers", Capture.scrubHeaders(api.headers(req)));
        request.put("query", Capture.captureMap(parseQuery(api.query(req))));
        Object vars = api.attribute(req, URI_VARS);
        Map<String, Object> pp = new LinkedHashMap<>();
        if (vars instanceof Map) {
            for (Map.Entry<?, ?> e : ((Map<?, ?>) vars).entrySet()) {
                String k = String.valueOf(e.getKey());
                pp.put(k, Capture.sensitiveKey(k) ? Capture.REDACTED : Capture.capture(e.getValue()));
            }
        }
        request.put("path_params", pp);
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("headers", Capture.scrubHeaders(api.responseHeaders(resp)));
        // Bodies: the raw servlet streams are not read (that would compete with the app). We use the
        // controller's @RequestBody argument and its return value instead - already captured and redacted.
        Object reqBody = null;
        Object respBody = null;
        String bodyNote = null;
        Map<String, Object> route = reg == null ? null : reg.route(routeId);
        Object handler = route == null ? null : route.get("handler");
        if (handler != null) {
            for (int i = 0; i < frames.size(); i++) {
                FrameRec f = frames.get(i);
                if (!handler.equals(f.fr.fnId)) continue;
                Map<String, Object> j = fj.get(i);
                Object bp = route.get("body_param");
                if (bp != null && f.args.containsKey(bp)) {
                    reqBody = f.args.get(bp);
                    bodyNote = "@RequestBody";
                }
                // 204/304 carry no body on the wire, whatever the controller returned
                if (j.get("exception") == null && j.containsKey("return") && status != 204 && status != 304) {
                    Object r = j.get("return");
                    if (r instanceof Map && ("ResponseEntity".equals(((Map<?, ?>) r).get("__type__"))
                            || "HttpEntity".equals(((Map<?, ?>) r).get("__type__")))) {
                        r = ((Map<?, ?>) r).get("body");
                    }
                    respBody = r;
                    response.put("body_source", "retorno do controller");
                }
                break;
            }
        }
        request.put("body", reqBody);
        if (bodyNote != null) request.put("body_source", bodyNote);
        response.put("body", respBody);

        Map<String, Object> ex = new LinkedHashMap<>();
        ex.put("id", id);
        ex.put("trace_id", traceId);
        ex.put("started_at", Math.round(startedAt * 1000) / 1000.0);
        ex.put("method", method);
        ex.put("path", path);
        ex.put("route_id", routeId);
        ex.put("status", status > 0 ? status : null);
        ex.put("duration_ms", Math.round(durUs) / 1000.0);
        ex.put("error", err);
        ex.put("frame_count", fj.size());
        ex.put("truncated", truncated);
        ex.put("backend", "javaagent");
        ex.put("request", request);
        ex.put("response", response);
        ex.put("frames", fj);
        return ex;
    }

    private static Throwable unwrap(Throwable t) {
        Throwable cur = t;
        for (int i = 0; i < 8 && cur.getCause() != null && cur.getCause() != cur; i++) {
            String n = cur.getClass().getName();
            if (!(n.endsWith("ServletException") || n.endsWith("NestedServletException")
                    || n.endsWith("UndeclaredThrowableException") || n.endsWith("InvocationTargetException"))) {
                break;
            }
            cur = cur.getCause();
        }
        return cur;
    }

    /** Frame id where the exception was first raised (deepest raising frame). */
    private static Integer errorOrigin(List<Map<String, Object>> frames) {
        List<Map<String, Object>> raising = new ArrayList<>();
        for (Map<String, Object> f : frames) if (f.get("exception") != null) raising.add(f);
        if (raising.isEmpty()) return null;
        for (int i = raising.size() - 1; i >= 0; i--) {
            Map<String, Object> f = raising.get(i);
            Object fid = f.get("id");
            boolean childRaised = false;
            for (Map<String, Object> c : raising) {
                if (fid.equals(c.get("parent"))) {
                    childRaised = true;
                    break;
                }
            }
            if (!childRaised) return (Integer) fid;
        }
        return (Integer) raising.get(raising.size() - 1).get("id");
    }

    static Map<String, Object> parseQuery(String q) {
        Map<String, Object> out = new LinkedHashMap<>();
        if (q == null || q.isEmpty()) return out;
        for (String part : q.split("&")) {
            if (part.isEmpty()) continue;
            int eq = part.indexOf('=');
            String k = eq >= 0 ? part.substring(0, eq) : part;
            String v = eq >= 0 ? part.substring(eq + 1) : "";
            try {
                k = URLDecoder.decode(k, StandardCharsets.UTF_8);
                v = URLDecoder.decode(v, StandardCharsets.UTF_8);
            } catch (Exception ignored) {
                // keep raw
            }
            out.put(k, v);
        }
        return out;
    }

    static String traceId(String traceparent) {
        if (traceparent != null) {
            String[] parts = traceparent.split("-");
            if (parts.length >= 4 && parts[1].length() == 32) return parts[1];
        }
        return hex(16);
    }
}
