package io.easyapi.agent.analysis;

import io.easyapi.agent.Config;
import io.easyapi.agent.Log;
import io.easyapi.agent.analysis.ProjectIndex.MethodDef;

import java.util.ArrayList;
import java.util.ArrayDeque;
import java.util.Collections;
import java.util.Deque;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Static model of the project: flows of every method, routes, middlewares. Built once, read-only after. */
public final class Registry {
    private static volatile Registry instance;
    private static final CountDownLatch READY = new CountDownLatch(1);
    private static volatile Throwable failure;

    public final Config cfg;
    public final ProjectIndex idx;
    private final Map<String, Flow> flows = new LinkedHashMap<>();
    private final List<RouteScanner.Route> routes;
    private final List<Map<String, Object>> middlewares;
    public final long buildMs;
    public int flowErrors;
    public int nodeCount;

    private Registry(Config cfg) {
        long t0 = System.nanoTime();
        this.cfg = cfg;
        List<java.nio.file.Path> roots = new ArrayList<>(cfg.sources);
        this.idx = ProjectIndex.build(roots, cfg.root, cfg.generated);
        CallResolver resolver = new CallResolver(idx);
        for (MethodDef m : idx.byFnId.values()) {
            Flow f;
            try {
                f = new FlowBuilder(m, resolver).build();
            } catch (Throwable t) {
                flowErrors++;
                Log.debug("flow failed for " + m.fnId + ": " + t);
                f = FlowBuilder.fallback(m);
            }
            nodeCount += f.nodes.size();
            flows.put(m.fnId, f);
        }
        RouteScanner rs = new RouteScanner(idx);
        List<RouteScanner.Route> r;
        List<Map<String, Object>> mw;
        try {
            r = rs.scan();
        } catch (Throwable t) {
            Log.internal("route scan", t);
            r = new ArrayList<>();
        }
        try {
            mw = rs.middlewares();
        } catch (Throwable t) {
            Log.internal("middleware scan", t);
            mw = new ArrayList<>();
        }
        this.routes = r;
        this.middlewares = mw;
        this.buildMs = (System.nanoTime() - t0) / 1_000_000;
    }

    public static void init(Config cfg) {
        try {
            Registry r = new Registry(cfg);
            instance = r;
            Log.info("static analysis: " + r.idx.files.size() + " files, " + r.idx.types.size() + " types, "
                    + r.flows.size() + " functions, " + r.nodeCount + " nodes, " + r.routes.size() + " routes, "
                    + r.middlewares.size() + " filters in " + r.buildMs + " ms"
                    + (r.idx.parseErrors > 0 ? " (" + r.idx.parseErrors + " files with parse problems)" : "")
                    + (r.flowErrors > 0 ? " (" + r.flowErrors + " flow errors)" : ""));
        } catch (Throwable t) {
            failure = t;
            Log.internal("static analysis", t);
        } finally {
            READY.countDown();
        }
    }

    public static Registry get() {
        return instance;
    }

    /** Waits for the background analysis (null on timeout/failure). */
    public static Registry await(long millis) {
        Registry r = instance;
        if (r != null) return r;
        try {
            READY.await(millis, TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        return instance;
    }

    public static boolean failed() {
        return failure != null;
    }

    public Flow flow(String fnId) {
        return fnId == null ? null : flows.get(fnId);
    }

    public int functionCount() {
        return flows.size();
    }

    public String runtimeFn(String binaryName, String method, int paramCount) {
        return idx.runtimeFn(binaryName, method, paramCount);
    }

    public List<Map<String, Object>> routesJson() {
        List<Map<String, Object>> out = new ArrayList<>(routes.size());
        for (RouteScanner.Route r : routes) out.add(r.json);
        return out;
    }

    public List<Map<String, Object>> middlewaresJson() {
        return Collections.unmodifiableList(middlewares);
    }

    /** fn_ids of user filters/interceptors (their callees are request-level frames). */
    public Set<String> middlewareFns() {
        Set<String> out = new HashSet<>();
        for (Map<String, Object> m : middlewares) {
            if (m.get("fn") != null) out.add((String) m.get("fn"));
        }
        return out;
    }

    public int routeCount() {
        return routes.size();
    }

    /** Route json by id (null if unknown). */
    public Map<String, Object> route(String id) {
        if (id == null) return null;
        for (RouteScanner.Route r : routes) if (r.id().equals(id)) return r.json;
        return null;
    }

    /** Route id for a request: prefer the framework's matched pattern, else regex matching on the path. */
    public String matchRoute(String method, String bestPattern, String path) {
        if (bestPattern != null && !bestPattern.isEmpty()) {
            String bp = RouteScanner.joinPath(bestPattern, "");
            RouteScanner.Route any = null;
            for (RouteScanner.Route r : routes) {
                if (!r.path.equals(bp)) continue;
                if (r.methods.contains(method)) return r.id();
                if (r.methods.contains("ANY")) any = r;
            }
            if (any != null) return any.id();
        }
        if (path == null) return null;
        RouteScanner.Route best = null;
        int bestScore = -1;
        for (RouteScanner.Route r : routes) {
            if (!r.methods.contains(method) && !r.methods.contains("ANY")) continue;
            if (!r.regex.matcher(path).matches()) continue;
            int score = r.path.replaceAll("\\{[^}]*}", "").length();
            if (score > bestScore) {
                best = r;
                bestScore = score;
            }
        }
        return best == null ? null : best.id();
    }

    /** BFS over resolved user calls starting at roots (python Registry.reachable). */
    public List<String> reachable(List<String> roots) {
        List<String> seen = new ArrayList<>();
        Deque<String> queue = new ArrayDeque<>(new LinkedHashSet<>(roots));
        Set<String> visited = new HashSet<>();
        while (!queue.isEmpty() && seen.size() < 5000) {
            String fid = queue.poll();
            if (fid == null || !visited.add(fid)) continue;
            Flow f = flows.get(fid);
            if (f == null) continue;
            seen.add(fid);
            for (Flow.Node n : f.nodes) {
                for (Flow.CallInfo c : n.calls) {
                    if ("user".equals(c.kind) && c.target != null && !visited.contains(c.target)) queue.add(c.target);
                }
            }
        }
        return seen;
    }
}
