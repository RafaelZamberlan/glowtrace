package io.glowtrace.agent;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeSet;
import java.util.stream.Stream;

/**
 * Agent options. Precedence: agent arguments ({@code key=value;key=value}) &gt;
 * system properties ({@code -Dglowtrace.key=value}) &gt; environment ({@code GLOWTRACE_KEY}) &gt; defaults.
 */
public final class Config {
    public static final String PREFIX = "/_glowtrace";
    public static final String VERSION = "0.3.2";

    public final List<String> packages = new ArrayList<>();
    public final List<Path> sources = new ArrayList<>();
    public Path root; // project root used for relative paths in fn_ids
    public int port = 7070;
    public String host = null; // bind address; default loopback (or 0.0.0.0 with a token)
    public String mode = "trace"; // trace | graph | off
    public String token = null;
    public String title = null;
    public boolean generated = true; // also index target/generated-sources (OpenAPI interfaces, MapStruct...)
    public int maxExecutions = 500;
    public boolean exposeHeader = true;
    // how much of each value is kept (max_depth / max_items / max_values / max_str)
    public int maxDepth = 8;
    public int maxItems = 25;
    public int maxValues = 400;
    public int maxStr = 400;

    public static Config parse(String agentArgs) {
        Map<String, String> args = new LinkedHashMap<>();
        if (agentArgs != null) {
            for (String part : agentArgs.split(";")) {
                part = part.trim();
                if (part.isEmpty()) continue;
                int eq = part.indexOf('=');
                if (eq <= 0) {
                    args.put(part.toLowerCase(), "true");
                } else {
                    args.put(part.substring(0, eq).trim().toLowerCase(), part.substring(eq + 1).trim());
                }
            }
        }
        Config c = new Config();
        String v;
        if ((v = opt(args, "mode")) != null) c.mode = v.trim().toLowerCase();
        if (!c.mode.equals("trace") && !c.mode.equals("graph") && !c.mode.equals("off")) {
            Log.warn("unknown mode '" + c.mode + "', using 'trace'");
            c.mode = "trace";
        }
        if ((v = opt(args, "packages")) != null) {
            for (String p : v.split("[,\\s]+")) {
                p = p.trim();
                if (p.endsWith(".*")) p = p.substring(0, p.length() - 2);
                if (p.endsWith(".")) p = p.substring(0, p.length() - 1);
                if (!p.isEmpty()) c.packages.add(p);
            }
        }
        if ((v = opt(args, "sources")) != null) {
            for (String s : v.split(",")) {
                s = s.trim();
                if (!s.isEmpty()) c.sources.add(Paths.get(s).toAbsolutePath().normalize());
            }
        }
        if (c.sources.isEmpty()) {
            Path guess = Paths.get("src", "main", "java").toAbsolutePath().normalize();
            if (Files.isDirectory(guess)) c.sources.add(guess);
        }
        if ((v = opt(args, "root")) != null) c.root = Paths.get(v).toAbsolutePath().normalize();
        if (c.root == null && !c.sources.isEmpty()) c.root = projectRootOf(c.sources.get(0));
        if ((v = opt(args, "port")) != null) {
            try {
                c.port = Integer.parseInt(v.trim());
            } catch (NumberFormatException e) {
                Log.warn("invalid port '" + v + "', using 7070");
            }
        }
        if ((v = opt(args, "host")) != null) c.host = v.trim();
        if ((v = opt(args, "token")) != null && !v.isEmpty()) c.token = v;
        if ((v = opt(args, "title")) != null) c.title = v;
        if ((v = opt(args, "generated")) != null) c.generated = !isFalse(v);
        if ((v = opt(args, "max_executions")) != null) {
            try {
                c.maxExecutions = Math.max(10, Integer.parseInt(v.trim()));
            } catch (NumberFormatException ignored) {
                // keep default
            }
        }
        if ((v = opt(args, "expose_header")) != null) c.exposeHeader = !isFalse(v);
        c.maxDepth = intOpt(args, "max_depth", c.maxDepth, 1, 200);
        c.maxItems = intOpt(args, "max_items", c.maxItems, 1, 10_000);
        c.maxValues = intOpt(args, "max_values", c.maxValues, 10, 1_000_000);
        c.maxStr = intOpt(args, "max_str", c.maxStr, 20, 1_000_000);
        if ((v = opt(args, "debug")) != null) Log.debug = !isFalse(v);
        if (c.title == null) {
            c.title = c.root != null && c.root.getFileName() != null ? c.root.getFileName().toString() : "API";
        }
        if (c.packages.isEmpty() && !c.sources.isEmpty()) {
            c.packages.addAll(inferPackages(c.sources));
            if (!c.packages.isEmpty()) Log.info("packages not given; inferred " + c.packages);
        }
        return c;
    }

    private static int intOpt(Map<String, String> args, String key, int def, int lo, int hi) {
        String v = opt(args, key);
        if (v == null) return def;
        try {
            return Math.max(lo, Math.min(hi, Integer.parseInt(v.trim())));
        } catch (NumberFormatException e) {
            Log.warn("invalid " + key + " '" + v + "', using " + def);
            return def;
        }
    }

    private static boolean isFalse(String v) {
        v = v.trim().toLowerCase();
        return v.equals("0") || v.equals("false") || v.equals("no") || v.equals("off");
    }

    private static String opt(Map<String, String> args, String key) {
        String v = args.get(key);
        if (v != null) return v;
        v = System.getProperty("glowtrace." + key);
        if (v != null && !v.isEmpty()) return v;
        v = System.getenv("GLOWTRACE_" + key.toUpperCase());
        if (v != null && !v.isEmpty()) return v;
        return null;
    }

    /** ".../proj/src/main/java" -> ".../proj"; ".../proj/src" -> ".../proj"; otherwise the dir itself. */
    public static Path projectRootOf(Path src) {
        Path p = src.toAbsolutePath().normalize();
        String s = p.toString().replace('\\', '/');
        for (String suffix : new String[] {"/src/main/java", "/src/main/kotlin", "/src"}) {
            if (s.endsWith(suffix)) {
                return Paths.get(s.substring(0, s.length() - suffix.length()));
            }
        }
        return p;
    }

    /** Shortest common package prefix of the source files (used when packages= is omitted). */
    static List<String> inferPackages(List<Path> sources) {
        TreeSet<String> pkgs = new TreeSet<>();
        for (Path src : sources) {
            if (!Files.isDirectory(src)) continue;
            try (Stream<Path> walk = Files.walk(src)) {
                walk.filter(p -> p.toString().endsWith(".java")).forEach(p -> {
                    Path rel = src.relativize(p.getParent() == null ? src : p.getParent());
                    String pkg = rel.toString().replace('\\', '.').replace('/', '.');
                    if (!pkg.isEmpty()) pkgs.add(pkg);
                });
            } catch (IOException ignored) {
                // best effort
            }
        }
        if (pkgs.isEmpty()) return List.of();
        String common = null;
        for (String p : pkgs) {
            if (common == null) {
                common = p;
                continue;
            }
            String[] a = common.split("\\.");
            String[] b = p.split("\\.");
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < Math.min(a.length, b.length) && a[i].equals(b[i]); i++) {
                if (sb.length() > 0) sb.append('.');
                sb.append(a[i]);
            }
            common = sb.toString();
        }
        if (common == null || common.isEmpty()) return new ArrayList<>(topLevel(pkgs));
        return List.of(common);
    }

    private static TreeSet<String> topLevel(TreeSet<String> pkgs) {
        TreeSet<String> out = new TreeSet<>();
        for (String p : pkgs) {
            String[] parts = p.split("\\.");
            out.add(parts.length >= 2 ? parts[0] + "." + parts[1] : parts[0]);
        }
        return out;
    }

    @Override
    public String toString() {
        return "mode=" + mode + " packages=" + packages + " sources=" + sources + " root=" + root + " port=" + port
                + (token != null ? " token=***" : "");
    }
}
