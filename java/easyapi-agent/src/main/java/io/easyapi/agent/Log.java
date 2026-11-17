package io.easyapi.agent;

import java.io.PrintWriter;
import java.io.StringWriter;
import java.util.concurrent.atomic.AtomicInteger;

/** Minimal stderr logger (the agent must not depend on the app's logging stack). */
public final class Log {
    private Log() {}

    public static volatile boolean debug = false;
    /** errors inside EasyAPI that were swallowed so the app was not affected. */
    public static final AtomicInteger INTERNAL_ERRORS = new AtomicInteger();

    public static void info(String msg) {
        System.err.println("[easyapi] " + msg);
    }

    public static void debug(String msg) {
        if (debug) System.err.println("[easyapi:debug] " + msg);
    }

    public static void warn(String msg) {
        System.err.println("[easyapi] WARN " + msg);
    }

    /** Count an internal error; print the first few stack traces only. */
    public static void internal(String where, Throwable t) {
        int n = INTERNAL_ERRORS.incrementAndGet();
        if (n <= 5 || debug) {
            StringWriter sw = new StringWriter();
            if (t != null) t.printStackTrace(new PrintWriter(sw));
            System.err.println("[easyapi] internal error in " + where + " (request unaffected): " + sw);
        }
    }
}
