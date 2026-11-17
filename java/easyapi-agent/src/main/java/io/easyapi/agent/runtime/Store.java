package io.easyapi.agent.runtime;

import java.util.ArrayList;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.ListIterator;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

/** In-memory ring buffer of the last N executions + observed caller->callee edges. */
public final class Store {
    private static final String[] SUMMARY_KEYS = {"id", "trace_id", "started_at", "method", "path", "route_id",
            "status", "duration_ms", "error", "frame_count"};

    public static final Store INSTANCE = new Store();

    private volatile int max = 500;
    private final LinkedHashMap<String, Map<String, Object>> data = new LinkedHashMap<>();
    private final ConcurrentHashMap<String, AtomicInteger> observed = new ConcurrentHashMap<>();

    public void setMax(int max) {
        this.max = max;
    }

    public void put(Map<String, Object> ex) {
        synchronized (data) {
            data.put((String) ex.get("id"), ex);
            Iterator<String> it = data.keySet().iterator();
            while (data.size() > max && it.hasNext()) {
                it.next();
                it.remove();
            }
        }
    }

    void observe(String src, String tgt) {
        observed.computeIfAbsent(src + "\u0000" + tgt, k -> new AtomicInteger()).incrementAndGet();
    }

    /** [src, tgt] -> count. */
    public Map<String[], Integer> observedEdges() {
        Map<String[], Integer> out = new LinkedHashMap<>();
        observed.forEach((k, v) -> {
            int i = k.indexOf('\u0000');
            out.put(new String[] {k.substring(0, i), k.substring(i + 1)}, v.get());
        });
        return out;
    }

    public static Map<String, Object> summary(Map<String, Object> ex) {
        Map<String, Object> s = new LinkedHashMap<>();
        for (String k : SUMMARY_KEYS) s.put(k, ex.get(k));
        return s;
    }

    private static boolean match(Map<String, Object> e, String route, String status) {
        if (route != null && !route.equals(e.get("route_id"))) return false;
        Object st = e.get("status");
        int code = st instanceof Integer ? (Integer) st : 0;
        boolean err = e.get("error") != null;
        if ("error".equals(status) && !(err || code >= 500)) return false;
        if ("ok".equals(status) && (err || code >= 400)) return false;
        return true;
    }

    public List<Map<String, Object>> list(String route, String status, int limit) {
        List<Map<String, Object>> items;
        synchronized (data) {
            items = new ArrayList<>(data.values());
        }
        List<Map<String, Object>> out = new ArrayList<>();
        ListIterator<Map<String, Object>> it = items.listIterator(items.size());
        while (it.hasPrevious() && out.size() < limit) {
            Map<String, Object> e = it.previous();
            if (match(e, route, status)) out.add(summary(e));
        }
        return out;
    }

    public Map<String, Object> get(String id) {
        synchronized (data) {
            return data.get(id);
        }
    }

    public int clear() {
        synchronized (data) {
            int n = data.size();
            data.clear();
            return n;
        }
    }

    public int size() {
        synchronized (data) {
            return data.size();
        }
    }
}
