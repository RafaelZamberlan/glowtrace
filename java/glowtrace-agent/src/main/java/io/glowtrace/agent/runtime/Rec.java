package io.glowtrace.agent.runtime;

import io.glowtrace.agent.Log;

import java.util.Map;

/**
 * Static entry points called from instrumented bytecode. Every method is a cheap ThreadLocal check when the
 * current thread is not inside a traced request, and never throws.
 */
public final class Rec {
    private Rec() {}

    static final ThreadLocal<Recorder> CTX = new ThreadLocal<>();
    private static volatile boolean tracing = false;
    private static volatile boolean exposeHeader = true;

    public static void configure(boolean trace, boolean header) {
        tracing = trace;
        exposeHeader = header;
    }

    /** True when the current thread records a request (used to avoid boxing args otherwise). */
    public static boolean active() {
        Recorder r = CTX.get();
        return r != null && r.busy == 0;
    }

    public static Object enter(String key, Object[] args) {
        Recorder r = CTX.get();
        if (r == null || r.busy > 0 || r.closed) return null;
        r.busy++;
        try {
            MethodTable.MethodInfo mi = MethodTable.byKey(key);
            return mi == null ? null : r.enter(mi, args);
        } catch (Throwable t) {
            Log.internal("enter", t);
            return null;
        } finally {
            r.busy--;
        }
    }

    public static void exit(Object frame, Object ret, Throwable thrown) {
        if (!(frame instanceof FrameRec)) return;
        FrameRec f = (FrameRec) frame;
        Recorder r = f.rec;
        r.busy++;
        try {
            r.exit(f, ret, thrown);
        } catch (Throwable t) {
            Log.internal("exit", t);
        } finally {
            r.busy--;
        }
    }

    /** Line probe: inserted after every LineNumber entry of instrumented methods. */
    public static void line(int mid, int line) {
        Recorder r = CTX.get();
        if (r == null || r.busy > 0) return;
        try {
            r.line(mid, line);
        } catch (Throwable t) {
            Log.internal("line", t);
        }
    }

    /** Probe inserted before every athrow of instrumented methods. */
    public static void thrown(Throwable ex, int mid) {
        Recorder r = CTX.get();
        if (r == null || r.busy > 0) return;
        r.busy++;
        try {
            r.thrown(ex, mid);
        } catch (Throwable t) {
            Log.internal("thrown", t);
        } finally {
            r.busy--;
        }
    }

    /** Outermost servlet entry (filter chain / HttpServlet.service) of a thread: start recording. */
    public static Object beginRequest(Object req, Object resp) {
        if (!tracing || CTX.get() != null) return null;
        try {
            ServletBridge.Api api = ServletBridge.api(req);
            if (api == null || !api.isRequestDispatch(req)) return null;
            String method = api.method(req);
            if (method == null || method.equals("OPTIONS")) return null;
            String forced = api.header(req, "x-glowtrace-trace");
            if (forced != null && (forced.trim().equals("0") || forced.trim().equalsIgnoreCase("false"))) return null;
            Recorder r = new Recorder();
            r.method = method;
            r.uri = api.uri(req);
            r.traceId = Recorder.traceId(api.header(req, "traceparent"));
            if (exposeHeader) api.setHeader(resp, "x-glowtrace-execution", r.id);
            CTX.set(r);
            return r;
        } catch (Throwable t) {
            Log.internal("begin request", t);
            return null;
        }
    }

    public static void endRequest(Object rec, Object req, Object resp, Throwable thrown) {
        if (!(rec instanceof Recorder)) return;
        Recorder r = (Recorder) rec;
        if (CTX.get() == r) CTX.remove();
        r.closed = true;
        try {
            ServletBridge.Api api = ServletBridge.api(req);
            if (api == null) return;
            Map<String, Object> ex = r.toExecution(api, req, resp, thrown);
            Store.INSTANCE.put(ex);
        } catch (Throwable t) {
            Log.internal("finish request", t);
        }
    }
}
