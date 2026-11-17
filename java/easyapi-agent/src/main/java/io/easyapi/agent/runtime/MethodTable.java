package io.easyapi.agent.runtime;

import io.easyapi.agent.analysis.Flow;
import io.easyapi.agent.analysis.Registry;

import java.util.Arrays;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Every instrumented method gets an int id at transform time (pushed as a constant by the line probes)
 * and a string key "binaryClass|method|descriptor" (pushed by the method advice).
 */
public final class MethodTable {
    private MethodTable() {}

    /** Runtime view of a flow: line -> node lookup without boxing. */
    public static final class FnRuntime {
        public final String fnId;
        public final List<String> params;
        public final String hash;
        private final int minLine;
        private final int[] lineToNode; // node + 1, 0 = no node
        /** user filter / interceptor: what it reaches through the framework chain is a root frame (like Python). */
        public final boolean middleware;
        private final java.util.Map<Integer, java.util.Set<String>> directCalls = new java.util.HashMap<>();

        /** True when the statement at {@code line} calls {@code fnId} directly (static resolution). */
        public boolean callsDirectly(int line, String fnId) {
            java.util.Set<String> s = directCalls.get(line);
            return s != null && s.contains(fnId);
        }

        FnRuntime(Flow f, boolean middleware) {
            this.fnId = f.fnId;
            this.params = f.params;
            this.hash = f.sourceHash;
            this.middleware = middleware;
            for (Flow.Node n : f.nodes) {
                for (Flow.CallInfo c : n.calls) {
                    if (c.target == null) continue;
                    for (int l = n.line; l <= Math.max(n.line, n.endLine); l++) {
                        directCalls.computeIfAbsent(l, k -> new java.util.HashSet<>()).add(c.target);
                    }
                }
            }
            int min = Integer.MAX_VALUE;
            int max = Integer.MIN_VALUE;
            for (Integer l : f.lines.keySet()) {
                min = Math.min(min, l);
                max = Math.max(max, l);
            }
            if (min > max) {
                minLine = 0;
                lineToNode = new int[0];
            } else {
                minLine = min;
                lineToNode = new int[max - min + 1];
                for (java.util.Map.Entry<Integer, Integer> e : f.lines.entrySet()) {
                    lineToNode[e.getKey() - min] = e.getValue() + 1;
                }
            }
        }

        /** node index owning a line, or -1. */
        public int node(int line) {
            int i = line - minLine;
            if (i < 0 || i >= lineToNode.length) return -1;
            return lineToNode[i] - 1;
        }
    }

    public static final class MethodInfo {
        public final int id;
        public final String key;
        public final String type; // binary class name
        public final String name;
        public final int paramCount;
        public final boolean lambda;
        public final String lambdaHost; // enclosing method name for lambda$host$N
        private volatile Object resolved; // FnRuntime or NONE

        MethodInfo(int id, String key, String type, String name, String desc) {
            this.id = id;
            this.key = key;
            this.type = type;
            this.name = name;
            this.paramCount = paramCount(desc);
            this.lambda = name.startsWith("lambda$");
            String host = null;
            if (lambda) {
                String[] parts = name.split("\\$");
                if (parts.length >= 3) host = parts[1];
            }
            this.lambdaHost = host;
        }

        /** fn runtime for this method or null (not a project function / trivial accessor / analysis pending). */
        public FnRuntime runtime() {
            Object r = resolved;
            if (r == NONE) return null;
            if (r != null) return (FnRuntime) r;
            Registry reg = Registry.await(30_000);
            if (reg == null) return null; // analysis not ready: retry next time
            String fid = lambda ? null : reg.runtimeFn(type, name, paramCount);
            Flow f = reg.flow(fid);
            FnRuntime fr = f == null ? null : new FnRuntime(f, reg.middlewareFns().contains(f.fnId));
            resolved = fr == null ? NONE : fr;
            return fr;
        }
    }

    private static final Object NONE = new Object();
    private static final ConcurrentHashMap<String, MethodInfo> BY_KEY = new ConcurrentHashMap<>();
    private static volatile MethodInfo[] byId = new MethodInfo[4096];
    private static int next = 0;

    public static String key(String type, String name, String desc) {
        return type + "|" + name + "|" + desc;
    }

    /** Called at transform time by the line probes (and lazily by the advice). */
    public static int register(String type, String name, String desc) {
        String k = key(type, name, desc);
        MethodInfo mi = BY_KEY.get(k);
        if (mi != null) return mi.id;
        synchronized (MethodTable.class) {
            mi = BY_KEY.get(k);
            if (mi != null) return mi.id;
            int id = next++;
            mi = new MethodInfo(id, k, type, name, desc);
            MethodInfo[] arr = byId;
            if (id >= arr.length) arr = Arrays.copyOf(arr, arr.length * 2);
            arr[id] = mi;
            byId = arr;
            BY_KEY.put(k, mi);
            return id;
        }
    }

    public static MethodInfo byKey(String key) {
        MethodInfo mi = BY_KEY.get(key);
        if (mi != null) return mi;
        String[] p = key.split("\\|", 3);
        if (p.length != 3) return null;
        return byId(register(p[0], p[1], p[2]));
    }

    public static MethodInfo byId(int id) {
        MethodInfo[] arr = byId;
        return id >= 0 && id < arr.length ? arr[id] : null;
    }

    static int paramCount(String desc) {
        int n = 0;
        int i = desc.indexOf('(') + 1;
        while (i < desc.length() && desc.charAt(i) != ')') {
            char c = desc.charAt(i);
            while (c == '[') c = desc.charAt(++i);
            if (c == 'L') i = desc.indexOf(';', i);
            i++;
            n++;
        }
        return n;
    }

    public static int size() {
        return BY_KEY.size();
    }
}
