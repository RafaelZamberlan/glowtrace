package io.easyapi.agent.runtime;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** One recorded call of a project method inside a request. */
final class FrameRec {
    final Recorder rec;
    final int id;
    final Integer parent;
    final Integer callLine;
    final MethodTable.MethodInfo mi;
    final MethodTable.FnRuntime fr;
    final long start;
    Long end;
    Map<String, Object> args = new LinkedHashMap<>();
    final List<long[]> path = new ArrayList<>();
    Object ret;
    Map<String, Object> exc;
    List<Map<String, Object>> raised;
    boolean truncated;
    Map<Integer, Integer> overflow;
    int last = -1; // last node appended to path
    int curLine; // last line executed in this frame

    FrameRec(Recorder rec, int id, FrameRec parent, MethodTable.FnRuntime fr, MethodTable.MethodInfo mi, long start) {
        this.rec = rec;
        this.id = id;
        this.parent = parent == null ? null : parent.id;
        this.callLine = parent == null || parent.curLine <= 0 ? null : parent.curLine;
        this.fr = fr;
        this.mi = mi;
        this.start = start;
    }

    Map<String, Object> toJson() {
        Map<String, Object> d = new LinkedHashMap<>();
        d.put("id", id);
        d.put("parent", parent);
        d.put("fn", fr.fnId);
        d.put("call_line", callLine);
        d.put("args", args);
        d.put("start_us", start);
        d.put("end_us", end);
        List<Object> p = new ArrayList<>(path.size());
        p.addAll(path);
        d.put("path", p);
        d.put("values", new ArrayList<>());
        d.put("hash", fr.hash);
        if (exc != null) d.put("exception", exc);
        else d.put("return", ret);
        if (raised != null && !raised.isEmpty()) d.put("raised", raised);
        if (truncated) {
            d.put("truncated", true);
            Map<String, Object> o = new LinkedHashMap<>();
            if (overflow != null) overflow.forEach((k, v) -> o.put(String.valueOf(k), v));
            d.put("overflow", o);
        }
        if (end == null) d.put("incomplete", true);
        return d;
    }
}
