package io.glowtrace.agent;

import io.glowtrace.agent.analysis.Registry;
import io.glowtrace.agent.instrument.Installer;
import io.glowtrace.agent.runtime.Rec;
import io.glowtrace.agent.runtime.Store;
import io.glowtrace.agent.server.UiServer;

import java.lang.instrument.Instrumentation;

/**
 * Glowtrace java agent.
 *
 * <pre>
 * java -javaagent:glowtrace-agent.jar=packages=org.example.app;sources=/path/src/main/java;port=7070 -jar app.jar
 * </pre>
 */
public final class GlowtraceAgent {
    private GlowtraceAgent() {}

    private static volatile boolean started;

    public static void premain(String args, Instrumentation inst) {
        start(args, inst);
    }

    public static void agentmain(String args, Instrumentation inst) {
        start(args, inst);
    }

    /**
     * Static analysis only (no app): {@code java -jar glowtrace-agent.jar "sources=...;root=..." [routes|map|function <id>|summary]}.
     */
    public static void main(String[] argv) {
        if (argv.length == 0) {
            System.out.println("usage: java -jar glowtrace-agent.jar \"sources=<dir>[,<dir>];root=<dir>\" [summary|routes|map|function <fn_id>|functions]");
            return;
        }
        Config cfg = Config.parse(argv[0]);
        Registry.init(cfg);
        Registry r = Registry.get();
        if (r == null) {
            System.exit(1);
            return;
        }
        String cmd = argv.length > 1 ? argv[1] : "summary";
        java.util.Map<String, Object> out = new java.util.LinkedHashMap<>();
        switch (cmd) {
            case "routes":
                out.put("routes", r.routesJson());
                out.put("middlewares", r.middlewaresJson());
                break;
            case "functions":
                out.put("functions", new java.util.ArrayList<>(r.idx.byFnId.keySet()));
                break;
            case "function":
                io.glowtrace.agent.analysis.Flow f = r.flow(argv.length > 2 ? argv[2] : "");
                if (f != null) {
                    out = f.toJson();
                    out.put("lines", f.lines);
                }
                break;
            case "map": {
                java.util.List<String> roots = new java.util.ArrayList<>();
                for (java.util.Map<String, Object> rt : r.routesJson()) {
                    if (rt.get("handler") != null) roots.add((String) rt.get("handler"));
                }
                out.put("reachable", r.reachable(roots));
                break;
            }
            default:
                out.put("files", r.idx.files.size());
                out.put("types", r.idx.types.size());
                out.put("functions", r.functionCount());
                out.put("nodes", r.nodeCount);
                out.put("routes", r.routeCount());
                out.put("parse_errors", r.idx.parseErrors);
                out.put("flow_errors", r.flowErrors);
        }
        java.io.PrintStream ps = new java.io.PrintStream(new java.io.FileOutputStream(java.io.FileDescriptor.out), true,
                java.nio.charset.StandardCharsets.UTF_8);
        ps.println(Json.write(out));
    }

    private static synchronized void start(String args, Instrumentation inst) {
        if (started) return;
        started = true;
        Config cfg;
        try {
            cfg = Config.parse(args);
        } catch (Throwable t) {
            Log.warn("invalid options, Glowtrace disabled: " + t);
            return;
        }
        if (cfg.mode.equals("off")) {
            Log.info("mode=off: disabled");
            return;
        }
        if (cfg.sources.isEmpty()) {
            Log.warn("no sources= given and ./src/main/java not found: the map will be empty");
        }
        Store.INSTANCE.setMax(cfg.maxExecutions);
        io.glowtrace.agent.runtime.Capture.setProjectPackages(cfg.packages);
        boolean trace = cfg.mode.equals("trace") && !cfg.packages.isEmpty();
        if (cfg.mode.equals("trace") && cfg.packages.isEmpty()) {
            Log.warn("no packages= given (and none inferred): runtime recording disabled, graph only");
        }
        Rec.configure(trace, cfg.exposeHeader);
        if (trace) {
            try {
                Installer.install(cfg, inst);
            } catch (Throwable t) {
                Rec.configure(false, false);
                Log.internal("installing instrumentation (recording disabled)", t);
            }
        }
        // the HTTP server + static analysis run on a daemon thread so the JVM can still exit normally;
        // threads created from it (the HTTP dispatcher) inherit the daemon flag.
        Thread init = new Thread(() -> {
            try {
                new UiServer(cfg).start();
            } catch (Throwable t) {
                Log.warn("could not start the UI server on port " + cfg.port + ": " + t);
            }
            Registry.init(cfg);
        }, "glowtrace-init");
        init.setDaemon(true);
        init.start();
    }
}
