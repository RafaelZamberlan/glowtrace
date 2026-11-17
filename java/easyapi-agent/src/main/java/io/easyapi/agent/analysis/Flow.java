package io.easyapi.agent.analysis;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Flow graph of one method (mirrors python/src/easyapi/static/flow.py FunctionFlow). */
public final class Flow {

    public static final class CallInfo {
        public final String expr;
        public final String kind; // user | external | stdlib | builtin | unresolved
        public final String target; // fn_id when user
        public final String lib; // when external/stdlib
        public int line;

        public CallInfo(String expr, String kind, String target, String lib) {
            this.expr = expr;
            this.kind = kind;
            this.target = target;
            this.lib = lib;
        }

        public boolean interesting() {
            return "user".equals(kind) || "external".equals(kind);
        }

        public Map<String, Object> toJson() {
            Map<String, Object> d = new LinkedHashMap<>();
            d.put("expr", expr);
            d.put("kind", kind);
            d.put("line", line);
            if (target != null) d.put("target", target);
            if (lib != null) d.put("lib", lib);
            return d;
        }
    }

    public static final class Node {
        public final int idx;
        public final String kind;
        public final String label;
        public final int line;
        public final int endLine;
        public final List<int[]> own = new ArrayList<>(); // line ranges observed at runtime
        public List<CallInfo> calls = new ArrayList<>();
        public List<String> watch = new ArrayList<>();
        public List<String> assigns = new ArrayList<>();
        public Integer tryParent;
        public Integer loopParent;

        Node(int idx, String kind, String label, int line, int endLine) {
            this.idx = idx;
            this.kind = kind;
            this.label = label;
            this.line = line;
            this.endLine = endLine;
        }

        public Map<String, Object> toJson() {
            Map<String, Object> d = new LinkedHashMap<>();
            d.put("id", idx);
            d.put("kind", kind);
            d.put("label", label);
            d.put("line", line);
            d.put("end_line", endLine);
            if (!calls.isEmpty()) {
                List<Object> cs = new ArrayList<>();
                for (CallInfo c : calls) cs.add(c.toJson());
                d.put("calls", cs);
            }
            if (!watch.isEmpty()) d.put("watch", watch);
            if (!assigns.isEmpty()) d.put("assigns", assigns);
            if (tryParent != null) d.put("try_parent", tryParent);
            if (loopParent != null) d.put("loop_parent", loopParent);
            return d;
        }
    }

    public static final class Edge {
        public final int source;
        public final int target;
        public final String kind;
        public final String label;

        Edge(int source, int target, String kind, String label) {
            this.source = source;
            this.target = target;
            this.kind = kind;
            this.label = label;
        }

        public Map<String, Object> toJson() {
            Map<String, Object> d = new LinkedHashMap<>();
            d.put("source", source);
            d.put("target", target);
            d.put("kind", kind);
            if (label != null && !label.isEmpty()) d.put("label", label);
            return d;
        }
    }

    public String fnId;
    public String qualname;
    public String relFile;
    public int line;
    public int endLine;
    public List<String> params = new ArrayList<>();
    public String doc;
    public String source;
    public int sourceStart;
    public String sourceHash;
    public List<Node> nodes = new ArrayList<>();
    public List<Edge> edges = new ArrayList<>();
    /** line -> node index (first node owning the line wins, like flow.py's setdefault). */
    public Map<Integer, Integer> lines = new HashMap<>();

    public Map<String, Object> toJson() {
        Map<String, Object> d = new LinkedHashMap<>();
        d.put("id", fnId);
        d.put("qualname", qualname);
        d.put("file", relFile);
        d.put("line", line);
        d.put("end_line", endLine);
        d.put("is_async", false);
        d.put("params", params);
        d.put("doc", doc);
        d.put("source", source);
        d.put("source_start", sourceStart);
        d.put("source_hash", sourceHash);
        List<Object> ns = new ArrayList<>(nodes.size());
        for (Node n : nodes) ns.add(n.toJson());
        d.put("nodes", ns);
        List<Object> es = new ArrayList<>(edges.size());
        for (Edge e : edges) es.add(e.toJson());
        d.put("edges", es);
        return d;
    }

    public int branches() {
        int n = 0;
        for (Node x : nodes) {
            if (x.kind.equals("if") || x.kind.equals("loop") || x.kind.equals("match") || x.kind.equals("try")) n++;
        }
        return n;
    }
}
