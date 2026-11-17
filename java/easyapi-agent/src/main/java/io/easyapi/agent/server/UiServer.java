package io.easyapi.agent.server;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import io.easyapi.agent.Config;
import io.easyapi.agent.Json;
import io.easyapi.agent.Log;
import io.easyapi.agent.analysis.Flow;
import io.easyapi.agent.analysis.Registry;
import io.easyapi.agent.runtime.Store;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.TreeSet;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** The /_easyapi JSON API + bundled UI on its own port (com.sun.net.httpserver). */
public final class UiServer {
    private static final String P = Config.PREFIX;
    private static final String FALLBACK_HTML = "<!doctype html><html lang=\"pt-BR\"><meta charset=\"utf-8\">"
            + "<title>EasyAPI</title><body style=\"font-family:system-ui;padding:2rem;max-width:720px\">"
            + "<h1>EasyAPI</h1><p>A interface não foi encontrada neste jar (rode <code>npm run build</code> em "
            + "<code>ui/</code> e recompile o agente).</p><p>API JSON: <a href=\"api/routes\">api/routes</a> · "
            + "<a href=\"api/executions\">api/executions</a> · <a href=\"api/map\">api/map</a></p></body></html>";

    private final Config cfg;
    private HttpServer server;

    public UiServer(Config cfg) {
        this.cfg = cfg;
    }

    public void start() throws IOException {
        InetAddress bind = cfg.host != null ? InetAddress.getByName(cfg.host)
                : cfg.token != null ? InetAddress.getByName("0.0.0.0") : InetAddress.getLoopbackAddress();
        server = HttpServer.create(new InetSocketAddress(bind, cfg.port), 0);
        ExecutorService pool = Executors.newFixedThreadPool(4, r -> {
            Thread t = new Thread(r, "easyapi-http");
            t.setDaemon(true);
            return t;
        });
        server.setExecutor(pool);
        server.createContext("/", this::handle);
        server.start();
        String host = bind.isAnyLocalAddress() ? "127.0.0.1" : bind.getHostAddress();
        Log.info("UI: http://" + host + ":" + cfg.port + P + "/  (" + cfg + ")");
    }

    // ------------------------------------------------------------------ dispatch

    private void handle(HttpExchange ex) {
        try {
            String path = ex.getRequestURI().getRawPath();
            Map<String, String> q = query(ex.getRequestURI().getRawQuery());
            boolean[] setCookie = {false};
            if (!allowed(ex, q, setCookie)) {
                json(ex, 403, detail("EasyAPI: acesso negado. Use EASYAPI_TOKEN ou acesse via localhost."));
                return;
            }
            if (setCookie[0]) {
                ex.getResponseHeaders().add("Set-Cookie",
                        "easyapi_token=" + cfg.token + "; HttpOnly; SameSite=Strict; Path=" + P);
            }
            String method = ex.getRequestMethod();
            if (path.equals("/") || path.equals(P)) {
                String qs = ex.getRequestURI().getRawQuery();
                redirect(ex, P + "/" + (qs != null ? "?" + qs : ""));
            } else if (path.equals(P + "/") || path.equals(P + "/index.html")) {
                byte[] html = resource("index.html");
                send(ex, 200, "text/html; charset=utf-8", html != null ? html : FALLBACK_HTML.getBytes(StandardCharsets.UTF_8));
            } else if (path.startsWith(P + "/assets/")) {
                asset(ex, path.substring((P + "/assets/").length()));
            } else if (path.equals(P + "/api/meta")) {
                json(ex, 200, meta());
            } else if (path.equals(P + "/api/routes")) {
                Registry r = registry(ex);
                if (r == null) return;
                Map<String, Object> d = new LinkedHashMap<>();
                d.put("routes", r.routesJson());
                d.put("middlewares", r.middlewaresJson());
                json(ex, 200, d);
            } else if (path.equals(P + "/api/function")) {
                function(ex, q.getOrDefault("id", ""));
            } else if (path.equals(P + "/api/map")) {
                Registry r = registry(ex);
                if (r == null) return;
                json(ex, 200, map(r));
            } else if (path.equals(P + "/api/executions")) {
                if (method.equals("DELETE")) {
                    Map<String, Object> d = new LinkedHashMap<>();
                    d.put("deleted", Store.INSTANCE.clear());
                    json(ex, 200, d);
                } else {
                    int limit = 100;
                    try {
                        limit = Math.max(1, Math.min(Integer.parseInt(q.getOrDefault("limit", "100")), 1000));
                    } catch (NumberFormatException ignored) {
                        // default
                    }
                    String route = q.get("route");
                    String status = q.get("status");
                    Map<String, Object> d = new LinkedHashMap<>();
                    d.put("executions", Store.INSTANCE.list(route == null || route.isEmpty() ? null : route,
                            status == null || status.isEmpty() ? null : status, limit));
                    json(ex, 200, d);
                }
            } else if (path.startsWith(P + "/api/executions/")) {
                String id = URLDecoder.decode(path.substring((P + "/api/executions/").length()), StandardCharsets.UTF_8);
                Map<String, Object> e = Store.INSTANCE.get(id);
                if (e == null) json(ex, 404, detail("execução não encontrada"));
                else json(ex, 200, e);
            } else {
                json(ex, 404, detail("not found"));
            }
        } catch (Throwable t) {
            Log.internal("ui server", t);
            try {
                json(ex, 500, detail("EasyAPI internal error: " + t.getClass().getSimpleName()));
            } catch (Throwable ignored) {
                // connection gone
            }
        } finally {
            ex.close();
        }
    }

    private boolean allowed(HttpExchange ex, Map<String, String> q, boolean[] setCookie) {
        if (cfg.token != null) {
            String supplied = ex.getRequestHeaders().getFirst("X-EasyAPI-Token");
            if (supplied == null) supplied = cookie(ex, "easyapi_token");
            String fromQuery = q.get("token");
            if (supplied == null) supplied = fromQuery;
            boolean ok = supplied != null && MessageDigest.isEqual(supplied.getBytes(StandardCharsets.UTF_8),
                    cfg.token.getBytes(StandardCharsets.UTF_8));
            setCookie[0] = ok && fromQuery != null;
            return ok;
        }
        InetAddress a = ex.getRemoteAddress() == null ? null : ex.getRemoteAddress().getAddress();
        return a != null && a.isLoopbackAddress();
    }

    private static String cookie(HttpExchange ex, String name) {
        List<String> cs = ex.getRequestHeaders().get("Cookie");
        if (cs == null) return null;
        for (String header : cs) {
            for (String part : header.split(";")) {
                String p = part.trim();
                if (p.startsWith(name + "=")) return p.substring(name.length() + 1);
            }
        }
        return null;
    }

    private Registry registry(HttpExchange ex) throws IOException {
        Registry r = Registry.await(60_000);
        if (r == null) {
            json(ex, 503, detail(Registry.failed() ? "EasyAPI: a análise estática falhou (veja o log)."
                    : "EasyAPI: análise estática em andamento, tente novamente."));
        }
        return r;
    }

    // ------------------------------------------------------------------ endpoints

    private Map<String, Object> meta() {
        Registry r = Registry.get();
        Map<String, Object> d = new LinkedHashMap<>();
        d.put("title", cfg.title);
        d.put("version", Config.VERSION);
        d.put("mode", cfg.mode);
        d.put("backend", cfg.mode.equals("trace") ? "javaagent" : null);
        d.put("runtime", "java " + System.getProperty("java.version"));
        d.put("platform", System.getProperty("os.name"));
        d.put("prefix", P);
        d.put("sample_rate", 1.0);
        d.put("route_count", r == null ? 0 : r.routeCount());
        d.put("internal_errors", Log.INTERNAL_ERRORS.get());
        return d;
    }

    private void function(HttpExchange ex, String id) throws IOException {
        Registry r = registry(ex);
        if (r == null) return;
        Flow f = r.flow(id);
        if (f == null) {
            json(ex, 404, detail("função não encontrada"));
            return;
        }
        Map<String, Object> d = f.toJson();
        TreeSet<String> observed = new TreeSet<>();
        for (Map.Entry<String[], Integer> e : Store.INSTANCE.observedEdges().entrySet()) {
            if (e.getKey()[0].equals(id)) observed.add(e.getKey()[1]);
        }
        d.put("observed_calls", new ArrayList<>(observed));
        json(ex, 200, d);
    }

    private static Map<String, Object> fnSummary(Flow f, boolean observedOnly) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", f.fnId);
        m.put("qualname", f.qualname);
        m.put("file", f.relFile);
        m.put("line", f.line);
        m.put("is_async", false);
        m.put("nodes", f.nodes.size());
        m.put("branches", observedOnly ? 0 : f.branches());
        TreeSet<String> ext = new TreeSet<>();
        if (!observedOnly) {
            for (Flow.Node n : f.nodes) {
                for (Flow.CallInfo c : n.calls) if ("external".equals(c.kind) && c.lib != null) ext.add(c.lib);
            }
        }
        m.put("external", new ArrayList<>(ext));
        if (observedOnly) m.put("observed_only", true);
        return m;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> map(Registry r) {
        List<Map<String, Object>> rts = r.routesJson();
        List<Map<String, Object>> mws = r.middlewaresJson();
        List<String> roots = new ArrayList<>();
        for (Map<String, Object> rt : rts) {
            if (rt.get("handler") != null) roots.add((String) rt.get("handler"));
            for (Map<String, Object> dep : (List<Map<String, Object>>) rt.get("dependencies")) roots.add((String) dep.get("fn"));
        }
        for (Map<String, Object> mw : mws) if (mw.get("fn") != null) roots.add((String) mw.get("fn"));
        List<String> fids = r.reachable(roots);
        LinkedHashSet<String> fidSet = new LinkedHashSet<>(fids);
        List<Map<String, Object>> functions = new ArrayList<>();
        Map<String, Map<String, Object>> edges = new LinkedHashMap<>();
        for (String fid : fids) {
            Flow f = r.flow(fid);
            if (f == null) continue;
            functions.add(fnSummary(f, false));
            for (Flow.Node n : f.nodes) {
                for (Flow.CallInfo c : n.calls) {
                    if ("user".equals(c.kind) && c.target != null && fidSet.contains(c.target)) {
                        edges.computeIfAbsent(fid + "\u0000" + c.target, k -> {
                            Map<String, Object> e = new LinkedHashMap<>();
                            e.put("source", fid);
                            e.put("target", c.target);
                            e.put("static", true);
                            e.put("observed", 0);
                            return e;
                        });
                    }
                }
            }
        }
        for (Map.Entry<String[], Integer> oe : Store.INSTANCE.observedEdges().entrySet()) {
            String s = oe.getKey()[0];
            String t = oe.getKey()[1];
            Map<String, Object> e = edges.get(s + "\u0000" + t);
            if (e == null) {
                e = new LinkedHashMap<>();
                e.put("source", s);
                e.put("target", t);
                e.put("static", false);
                e.put("observed", oe.getValue());
                edges.put(s + "\u0000" + t, e);
                for (String x : new String[] {s, t}) {
                    if (!fidSet.contains(x)) {
                        Flow f = r.flow(x);
                        if (f != null) {
                            fidSet.add(x);
                            functions.add(fnSummary(f, true));
                        }
                    }
                }
            } else {
                e.put("observed", oe.getValue());
            }
        }
        Map<String, Object> d = new LinkedHashMap<>();
        d.put("routes", rts);
        d.put("middlewares", mws);
        d.put("functions", functions);
        d.put("edges", new ArrayList<>(edges.values()));
        return d;
    }

    // ------------------------------------------------------------------ static files

    private static byte[] resource(String rel) throws IOException {
        if (rel.contains("..") || rel.contains("\\") || rel.startsWith("/")) return null;
        try (InputStream in = UiServer.class.getClassLoader().getResourceAsStream("easyapi-ui/" + rel)) {
            if (in == null) return null;
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            in.transferTo(bos);
            return bos.toByteArray();
        }
    }

    private void asset(HttpExchange ex, String rel) throws IOException {
        byte[] b = resource("assets/" + rel);
        if (b == null) {
            send(ex, 404, "text/plain; charset=utf-8", "not found".getBytes(StandardCharsets.UTF_8));
            return;
        }
        send(ex, 200, contentType(rel), b);
    }

    private static String contentType(String name) {
        String n = name.toLowerCase();
        if (n.endsWith(".js") || n.endsWith(".mjs")) return "text/javascript; charset=utf-8";
        if (n.endsWith(".css")) return "text/css; charset=utf-8";
        if (n.endsWith(".svg")) return "image/svg+xml";
        if (n.endsWith(".png")) return "image/png";
        if (n.endsWith(".ico")) return "image/x-icon";
        if (n.endsWith(".woff2")) return "font/woff2";
        if (n.endsWith(".woff")) return "font/woff";
        if (n.endsWith(".json") || n.endsWith(".map")) return "application/json";
        if (n.endsWith(".html")) return "text/html; charset=utf-8";
        return "application/octet-stream";
    }

    // ------------------------------------------------------------------ helpers

    private static Map<String, Object> detail(String msg) {
        Map<String, Object> d = new LinkedHashMap<>();
        d.put("detail", msg);
        return d;
    }

    private static void json(HttpExchange ex, int status, Object body) throws IOException {
        send(ex, status, "application/json", Json.write(body).getBytes(StandardCharsets.UTF_8));
    }

    private static void redirect(HttpExchange ex, String location) throws IOException {
        ex.getResponseHeaders().set("Location", location);
        ex.getResponseHeaders().set("Cache-Control", "no-store");
        ex.sendResponseHeaders(307, -1);
    }

    private static void send(HttpExchange ex, int status, String contentType, byte[] body) throws IOException {
        ex.getResponseHeaders().set("Content-Type", contentType);
        ex.getResponseHeaders().set("Cache-Control", "no-store");
        ex.getResponseHeaders().set("X-Content-Type-Options", "nosniff");
        boolean head = ex.getRequestMethod().equals("HEAD");
        ex.sendResponseHeaders(status, head ? -1 : body.length);
        if (!head) {
            try (OutputStream os = ex.getResponseBody()) {
                os.write(body);
            }
        }
    }

    private static Map<String, String> query(String raw) {
        Map<String, String> out = new LinkedHashMap<>();
        if (raw == null || raw.isEmpty()) return out;
        for (String part : raw.split("&")) {
            if (part.isEmpty()) continue;
            int eq = part.indexOf('=');
            String k = eq >= 0 ? part.substring(0, eq) : part;
            String v = eq >= 0 ? part.substring(eq + 1) : "";
            out.put(URLDecoder.decode(k, StandardCharsets.UTF_8), URLDecoder.decode(v, StandardCharsets.UTF_8));
        }
        return out;
    }
}
