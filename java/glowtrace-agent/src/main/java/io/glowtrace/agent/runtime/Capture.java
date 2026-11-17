package io.glowtrace.agent.runtime;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.lang.reflect.Proxy;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.util.ArrayList;
import java.util.Collection;
import java.util.IdentityHashMap;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Side-effect-free value capture with PII / secret redaction (port of python runtime/capture.py).
 * Never calls toString()/getters of arbitrary objects: objects are read through their declared fields.
 */
public final class Capture {
    private Capture() {}

    public static final String REDACTED = "[REDACTED]";
    // limits (configurable: max_depth / max_items / max_values / max_str, see Config)
    /** nesting levels opened; BUDGET is what bounds the size of a captured value */
    static volatile int MAX_DEPTH = 8;
    static volatile int MAX_ITEMS = 25;
    static volatile int MAX_STR = 400;
    /** values read per captured value (all levels together) */
    static volatile int BUDGET = 400;

    public static void setLimits(int depth, int items, int values, int str) {
        MAX_DEPTH = depth;
        MAX_ITEMS = items;
        BUDGET = values;
        MAX_STR = str;
    }

    public static Map<String, Object> limits() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("max_depth", MAX_DEPTH);
        m.put("max_items", MAX_ITEMS);
        m.put("max_values", BUDGET);
        m.put("max_str", MAX_STR);
        return m;
    }

    private static final String[] STRONG_KEY_PARTS = {"password", "passwd", "senha", "secret", "token", "apikey",
            "api_key", "authorization", "cookie", "privatekey", "private_key", "credential", "cpf", "cnpj",
            "creditcard", "cartao", "cartão"};
    private static final Set<String> EXACT_KEY_TOKENS = Set.of("pwd", "pin", "cvv", "cvc", "rg", "otp", "auth",
            "session", "sessionid", "signature", "card", "jwt", "bearer");

    private static final Pattern JWT = Pattern.compile("eyJ[A-Za-z0-9_-]{5,}\\.[A-Za-z0-9_-]{5,}\\.[A-Za-z0-9_-]*");
    private static final Pattern BEARER = Pattern.compile("(?i)\\b(bearer|basic)\\s+[A-Za-z0-9._~+/=-]{8,}");
    private static final Pattern CPF = Pattern.compile("(?<!\\d)\\d{3}\\.?\\d{3}\\.?\\d{3}-?\\d{2}(?!\\d)");
    private static final Pattern CNPJ = Pattern.compile("(?<!\\d)\\d{2}\\.?\\d{3}\\.?\\d{3}/?\\d{4}-?\\d{2}(?!\\d)");
    private static final Pattern CARD = Pattern.compile("(?<!\\d)(?:\\d[ -]?){12,18}\\d(?!\\d)");
    private static final Pattern EMAIL =
            Pattern.compile("\\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\\.[A-Za-z]{2,})\\b");
    private static final Pattern CAMEL = Pattern.compile("(?<=[a-z0-9])(?=[A-Z])");
    private static final Pattern SPLIT = Pattern.compile("[^a-z0-9]+");

    private static final Set<String> SENSITIVE_HEADERS = Set.of("authorization", "proxy-authorization", "cookie",
            "set-cookie", "x-api-key", "x-auth-token", "x-csrf-token", "x-glowtrace-token");

    private static final String[] FRAMEWORK_PREFIXES = {"org.springframework.", "org.apache.", "org.hibernate.",
            "jakarta.", "javax.", "com.fasterxml.", "io.micrometer.", "reactor.", "io.netty.", "com.zaxxer.",
            "org.slf4j.", "ch.qos.", "org.h2.", "com.mysql.", "org.postgresql.", "java.", "jdk.", "sun.", "com.sun.",
            "kotlin.", "org.eclipse.", "io.undertow.", "org.thymeleaf.", "com.google.", "net.bytebuddy.",
            "org.aspectj.", "org.mapstruct.", "io.swagger.", "org.openapitools.", "io.glowtrace."};

    private static final Map<String, Boolean> KEY_CACHE = new ConcurrentHashMap<>();
    /** containers being opened on this thread right now: an object graph that points back to itself stops here */
    private static final ThreadLocal<IdentityHashMap<Object, Boolean>> PATH = ThreadLocal.withInitial(IdentityHashMap::new);
    /** project package prefixes ("org.example.app."): always captured by fields, even under org.springframework. */
    private static volatile String[] projectPrefixes = new String[0];

    public static void setProjectPackages(List<String> packages) {
        String[] p = new String[packages.size()];
        for (int i = 0; i < p.length; i++) p[i] = packages.get(i) + ".";
        projectPrefixes = p;
    }

    private static boolean isProject(String cn) {
        for (String p : projectPrefixes) if (cn.startsWith(p)) return true;
        return false;
    }

    // ------------------------------------------------------------------ keys

    public static boolean sensitiveKey(String key) {
        if (key == null) return false;
        Boolean hit = KEY_CACHE.get(key);
        if (hit != null) return hit;
        String low = key.toLowerCase();
        String compact = low.replace("-", "").replace("_", "");
        boolean res = false;
        for (String p : STRONG_KEY_PARTS) {
            if (compact.contains(p.replace("_", ""))) {
                res = true;
                break;
            }
        }
        if (!res) {
            String snake = CAMEL.matcher(key).replaceAll("_").toLowerCase();
            for (String tok : SPLIT.split(snake)) {
                if (EXACT_KEY_TOKENS.contains(tok)) {
                    res = true;
                    break;
                }
            }
        }
        if (KEY_CACHE.size() < 10000) KEY_CACHE.put(key, res);
        return res;
    }

    // ------------------------------------------------------------------ strings

    public static String scrubText(String text) {
        if (text == null || text.isEmpty()) return text;
        text = JWT.matcher(text).replaceAll("[JWT]");
        text = BEARER.matcher(text).replaceAll(m -> Matcher.quoteReplacement(m.group(1) + " " + REDACTED));
        text = CNPJ.matcher(text).replaceAll(m -> cnpjOk(digits(m.group())) ? "[CNPJ]" : Matcher.quoteReplacement(m.group()));
        text = CPF.matcher(text).replaceAll(m -> cpfOk(digits(m.group())) ? "[CPF]" : Matcher.quoteReplacement(m.group()));
        text = CARD.matcher(text).replaceAll(m -> luhnOk(digits(m.group())) ? "[CARD]" : Matcher.quoteReplacement(m.group()));
        text = EMAIL.matcher(text).replaceAll(m -> Matcher.quoteReplacement(m.group(1) + "***@" + m.group(2)));
        return text;
    }

    private static String digits(String s) {
        StringBuilder sb = new StringBuilder(s.length());
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c >= '0' && c <= '9') sb.append(c);
        }
        return sb.toString();
    }

    private static boolean allSame(String d) {
        for (int i = 1; i < d.length(); i++) if (d.charAt(i) != d.charAt(0)) return false;
        return true;
    }

    static boolean cpfOk(String d) {
        if (d.length() != 11 || allSame(d)) return false;
        for (int n = 9; n <= 10; n++) {
            int s = 0;
            for (int i = 0; i < n; i++) s += (d.charAt(i) - '0') * (n + 1 - i);
            int dv = (s * 10) % 11 % 10;
            if (dv != d.charAt(n) - '0') return false;
        }
        return true;
    }

    static boolean cnpjOk(String d) {
        if (d.length() != 14 || allSame(d)) return false;
        int[] w1 = {5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2};
        int[] w2 = {6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2};
        int[][] ws = {w1, w2};
        for (int k = 0; k < 2; k++) {
            int[] w = ws[k];
            int n = 12 + k;
            int s = 0;
            for (int i = 0; i < n; i++) s += (d.charAt(i) - '0') * w[i];
            int dv = s % 11 < 2 ? 0 : 11 - s % 11;
            if (dv != d.charAt(n) - '0') return false;
        }
        return true;
    }

    static boolean luhnOk(String d) {
        if (d.length() < 13 || d.length() > 19) return false;
        int total = 0;
        for (int i = 0; i < d.length(); i++) {
            int x = d.charAt(d.length() - 1 - i) - '0';
            if (i % 2 == 1) {
                x *= 2;
                if (x > 9) x -= 9;
            }
            total += x;
        }
        return total % 10 == 0;
    }

    static String str(String s) {
        if (s.length() > MAX_STR) s = s.substring(0, MAX_STR) + "…(+" + (s.length() - MAX_STR) + ")";
        return scrubText(s);
    }

    // ------------------------------------------------------------------ values

    public static Object capture(Object v) {
        int[] budget = {BUDGET};
        try {
            return cap(v, 0, budget);
        } catch (Throwable t) {
            return "<capture error: " + t.getClass().getSimpleName() + ">";
        }
    }

    /** names[i] -> values[i], with key redaction and a shared budget. */
    public static Map<String, Object> captureNamed(List<String> names, Object[] values) {
        Map<String, Object> out = new LinkedHashMap<>();
        if (values == null) return out;
        int[] budget = {BUDGET};
        for (int i = 0; i < values.length; i++) {
            String k = names != null && i < names.size() ? names.get(i) : "arg" + i;
            if (sensitiveKey(k)) {
                out.put(k, REDACTED);
                continue;
            }
            try {
                out.put(k, cap(values[i], 0, budget));
            } catch (Throwable t) {
                out.put(k, "<capture error: " + t.getClass().getSimpleName() + ">");
            }
        }
        return out;
    }

    public static Map<String, Object> captureMap(Map<String, ?> m) {
        Map<String, Object> out = new LinkedHashMap<>();
        if (m == null) return out;
        int[] budget = {BUDGET};
        for (Map.Entry<String, ?> e : m.entrySet()) {
            String k = e.getKey();
            out.put(k, sensitiveKey(k) ? REDACTED : safeCap(e.getValue(), budget));
        }
        return out;
    }

    private static Object safeCap(Object v, int[] budget) {
        try {
            return cap(v, 0, budget);
        } catch (Throwable t) {
            return "<capture error: " + t.getClass().getSimpleName() + ">";
        }
    }

    private static Object cap(Object v, int depth, int[] budget) {
        if (--budget[0] < 0) return "…";
        if (v == null || v instanceof Boolean) return v;
        if (v instanceof Integer || v instanceof Short || v instanceof Byte) return v;
        if (v instanceof Long) {
            long l = (Long) v;
            return Math.abs(l) < (1L << 53) ? v : Long.toString(l);
        }
        if (v instanceof Double) {
            double d = (Double) v;
            return Double.isNaN(d) || Double.isInfinite(d) ? Double.toString(d) : v;
        }
        if (v instanceof Float) {
            float f = (Float) v;
            return Float.isNaN(f) || Float.isInfinite(f) ? Float.toString(f) : v;
        }
        if (v instanceof String) return str((String) v);
        if (v instanceof Character) return str(v.toString());
        if (v instanceof BigInteger) {
            BigInteger b = (BigInteger) v;
            return b.bitLength() < 53 ? (Object) b.longValue() : b.toString();
        }
        if (v instanceof BigDecimal) return ((BigDecimal) v).toPlainString();
        if (v instanceof Enum) return ((Enum<?>) v).getDeclaringClass().getSimpleName() + "." + ((Enum<?>) v).name();
        Class<?> c = v.getClass();
        String cn = c.getName();
        if (v instanceof CharSequence && cn.startsWith("java.")) return str(v.toString());
        if (v instanceof byte[]) return "<bytes " + ((byte[]) v).length + ">";
        if (v instanceof char[]) return str(new String((char[]) v));
        if (safeToString(cn)) return str(v.toString());
        if (v instanceof java.util.Date) return ((java.util.Date) v).toInstant().toString();
        if (v instanceof Class) return "<class " + ((Class<?>) v).getSimpleName() + ">";
        if (v instanceof Optional) {
            Optional<?> o = (Optional<?>) v;
            return o.isPresent() ? cap(o.get(), depth, budget) : null;
        }
        if (v instanceof Throwable) {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("__type__", c.getSimpleName());
            String msg = null;
            try {
                msg = ((Throwable) v).getMessage();
            } catch (Throwable ignored) {
                // ignore
            }
            out.put("message", msg == null ? null : str(msg));
            return out;
        }
        if (cn.contains("$HibernateProxy") || cn.contains("$$_javassist") || cn.contains("$ByteBuddy$")) {
            Class<?> sup = c.getSuperclass();
            return "<LazyProxy " + (sup != null ? sup.getSimpleName() : c.getSimpleName()) + ">";
        }
        if (cn.startsWith("org.hibernate.collection.")) {
            if (!initialized(v)) return "<LazyCollection>";
        }
        if (Proxy.isProxyClass(c)) return "<Proxy>";
        if (cn.contains("$$Lambda") || c.isSynthetic() && cn.contains("$$")) return "<lambda>";
        if (cn.contains("$$")) {
            Class<?> sup = c.getSuperclass();
            return "<" + (sup != null ? sup.getSimpleName() : c.getSimpleName()) + " proxy>";
        }
        if (depth >= MAX_DEPTH) return "<" + c.getSimpleName() + ">";
        IdentityHashMap<Object, Boolean> path = PATH.get();
        if (path.containsKey(v)) return "<ciclo " + c.getSimpleName() + ">";
        path.put(v, Boolean.TRUE);
        try {
            return nested(v, c, cn, depth, budget);
        } finally {
            path.remove(v);
        }
    }

    private static Object nested(Object v, Class<?> c, String cn, int depth, int[] budget) {
        if (v instanceof Map) {
            Map<?, ?> m = (Map<?, ?>) v;
            Map<String, Object> out = new LinkedHashMap<>();
            int i = 0;
            int size = m.size();
            for (Map.Entry<?, ?> e : m.entrySet()) {
                if (i >= MAX_ITEMS) {
                    out.put("…", "+" + (size - i) + " itens");
                    break;
                }
                Object k = e.getKey();
                String ks = k instanceof String ? (String) k
                        : (k instanceof Number || k instanceof Boolean || k instanceof Character) ? String.valueOf(k)
                        : k instanceof Enum ? ((Enum<?>) k).name()
                        : "<" + (k == null ? "null" : k.getClass().getSimpleName()) + ">";
                out.put(ks, sensitiveKey(ks) ? REDACTED : cap(e.getValue(), depth + 1, budget));
                i++;
            }
            return out;
        }
        if (v instanceof Collection) {
            Collection<?> col = (Collection<?>) v;
            List<Object> out = new ArrayList<>();
            int size = col.size();
            Iterator<?> it = col.iterator();
            for (int i = 0; i < MAX_ITEMS && it.hasNext(); i++) out.add(cap(it.next(), depth + 1, budget));
            if (size > MAX_ITEMS) out.add("…(+" + (size - MAX_ITEMS) + ")");
            return out;
        }
        if (c.isArray()) {
            int n = java.lang.reflect.Array.getLength(v);
            List<Object> out = new ArrayList<>();
            for (int i = 0; i < Math.min(n, MAX_ITEMS); i++) {
                out.add(cap(java.lang.reflect.Array.get(v, i), depth + 1, budget));
            }
            if (n > MAX_ITEMS) out.add("…(+" + (n - MAX_ITEMS) + ")");
            return out;
        }
        if (isServletObject(c)) return "<" + c.getSimpleName() + ">";
        if (cn.equals("org.springframework.http.ResponseEntity") || cn.equals("org.springframework.http.HttpEntity")) {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("__type__", c.getSimpleName());
            Object status = readField(v, "status");
            if (status != null) {
                Object code = readField(status, "value");
                out.put("status", code instanceof Integer ? code : cap(status, depth + 1, budget));
            }
            out.put("body", cap(readField(v, "body"), depth + 1, budget));
            return out;
        }
        if (cn.startsWith("org.springframework.data.domain.") && (cn.endsWith("PageImpl") || cn.endsWith("SliceImpl"))) {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("__type__", c.getSimpleName());
            out.put("content", cap(readField(v, "content"), depth + 1, budget));
            Object total = readField(v, "total");
            if (total != null) out.put("total", cap(total, depth + 1, budget));
            return out;
        }
        if (!isProject(cn) && isFramework(cn)) return "<" + c.getSimpleName() + ">";
        return object(v, c, depth, budget);
    }

    private static boolean safeToString(String cn) {
        return cn.startsWith("java.time.") || cn.equals("java.util.UUID") || cn.equals("java.net.URI")
                || cn.equals("java.net.URL") || cn.equals("java.util.Locale") || cn.equals("java.util.Currency")
                || cn.startsWith("java.util.concurrent.atomic.Atomic") && !cn.contains("Reference") && !cn.contains("Array")
                || cn.equals("java.io.File") || cn.startsWith("sun.nio.fs.") || cn.equals("java.sql.Date")
                || cn.equals("java.sql.Timestamp") || cn.equals("java.sql.Time");
    }

    private static boolean isFramework(String cn) {
        for (String p : FRAMEWORK_PREFIXES) if (cn.startsWith(p)) return true;
        return false;
    }

    private static boolean isServletObject(Class<?> c) {
        for (Class<?> x = c; x != null && x != Object.class; x = x.getSuperclass()) {
            for (Class<?> i : x.getInterfaces()) {
                String n = i.getName();
                if (n.startsWith("jakarta.servlet.") || n.startsWith("javax.servlet.")) return true;
            }
        }
        return false;
    }

    private static boolean initialized(Object v) {
        try {
            Method m = v.getClass().getMethod("wasInitialized");
            Object r = m.invoke(v);
            return Boolean.TRUE.equals(r);
        } catch (Throwable t) {
            return false;
        }
    }

    private static Object readField(Object v, String name) {
        for (Class<?> x = v.getClass(); x != null && x != Object.class; x = x.getSuperclass()) {
            try {
                Field f = x.getDeclaredField(name);
                if (Modifier.isStatic(f.getModifiers())) return null;
                f.setAccessible(true);
                return f.get(v);
            } catch (NoSuchFieldException e) {
                // try superclass
            } catch (Throwable t) {
                return null;
            }
        }
        return null;
    }

    private static final ClassValue<Field[]> FIELDS = new ClassValue<>() {
        @Override
        protected Field[] computeValue(Class<?> type) {
            List<Field> out = new ArrayList<>();
            List<Class<?>> chain = new ArrayList<>();
            for (Class<?> x = type; x != null && x != Object.class && !x.getName().startsWith("java."); x = x.getSuperclass()) {
                chain.add(0, x);
            }
            for (Class<?> x : chain) {
                Field[] fs;
                try {
                    fs = x.getDeclaredFields();
                } catch (Throwable t) {
                    continue;
                }
                for (Field f : fs) {
                    int mod = f.getModifiers();
                    if (Modifier.isStatic(mod) || f.isSynthetic() || f.getName().startsWith("$")) continue;
                    try {
                        f.setAccessible(true);
                        out.add(f);
                    } catch (Throwable t) {
                        // module-protected: skip
                    }
                }
            }
            return out.toArray(new Field[0]);
        }
    };

    private static Object object(Object v, Class<?> c, int depth, int[] budget) {
        Field[] fields = FIELDS.get(c);
        if (fields.length == 0) return "<" + c.getSimpleName() + ">";
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("__type__", c.getSimpleName());
        int count = 0;
        for (Field f : fields) {
            if (count >= MAX_ITEMS) {
                out.put("…", "…");
                break;
            }
            String k = f.getName();
            if (sensitiveKey(k)) {
                out.put(k, REDACTED);
            } else {
                Object val;
                try {
                    val = f.get(v);
                } catch (Throwable t) {
                    continue;
                }
                out.put(k, cap(val, depth + 1, budget));
            }
            count++;
        }
        return out;
    }

    // ------------------------------------------------------------------ headers

    public static Map<String, Object> scrubHeaders(Map<String, String> headers) {
        Map<String, Object> out = new LinkedHashMap<>();
        for (Map.Entry<String, String> e : headers.entrySet()) {
            String key = e.getKey().toLowerCase();
            if (SENSITIVE_HEADERS.contains(key) || sensitiveKey(key)) {
                out.put(key, REDACTED);
            } else {
                String val = e.getValue() == null ? "" : e.getValue();
                out.put(key, scrubText(val.length() > 300 ? val.substring(0, 300) : val));
            }
        }
        return out;
    }
}
