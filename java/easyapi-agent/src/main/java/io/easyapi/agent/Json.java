package io.easyapi.agent;

import java.math.BigDecimal;
import java.math.BigInteger;
import java.util.Collection;
import java.util.Map;

/** Tiny JSON writer for Map / List / String / Number / Boolean / null / primitive arrays. */
public final class Json {
    private Json() {}

    public static String write(Object o) {
        StringBuilder sb = new StringBuilder(256);
        write(sb, o);
        return sb.toString();
    }

    public static void write(StringBuilder sb, Object o) {
        if (o == null) {
            sb.append("null");
        } else if (o instanceof String) {
            str(sb, (String) o);
        } else if (o instanceof Boolean) {
            sb.append(((Boolean) o).booleanValue() ? "true" : "false");
        } else if (o instanceof Double) {
            dbl(sb, (Double) o);
        } else if (o instanceof Float) {
            float f = (Float) o;
            if (Float.isNaN(f) || Float.isInfinite(f)) str(sb, Float.toString(f));
            else sb.append(Float.toString(f));
        } else if (o instanceof Integer || o instanceof Long || o instanceof Short || o instanceof Byte
                || o instanceof BigInteger) {
            sb.append(o.toString());
        } else if (o instanceof BigDecimal) {
            sb.append(((BigDecimal) o).toString());
        } else if (o instanceof Map) {
            sb.append('{');
            boolean first = true;
            for (Map.Entry<?, ?> e : ((Map<?, ?>) o).entrySet()) {
                if (!first) sb.append(',');
                first = false;
                str(sb, String.valueOf(e.getKey()));
                sb.append(':');
                write(sb, e.getValue());
            }
            sb.append('}');
        } else if (o instanceof Collection) {
            sb.append('[');
            boolean first = true;
            for (Object x : (Collection<?>) o) {
                if (!first) sb.append(',');
                first = false;
                write(sb, x);
            }
            sb.append(']');
        } else if (o instanceof long[]) {
            long[] a = (long[]) o;
            sb.append('[');
            for (int i = 0; i < a.length; i++) {
                if (i > 0) sb.append(',');
                sb.append(a[i]);
            }
            sb.append(']');
        } else if (o instanceof int[]) {
            int[] a = (int[]) o;
            sb.append('[');
            for (int i = 0; i < a.length; i++) {
                if (i > 0) sb.append(',');
                sb.append(a[i]);
            }
            sb.append(']');
        } else if (o instanceof Object[]) {
            Object[] a = (Object[]) o;
            sb.append('[');
            for (int i = 0; i < a.length; i++) {
                if (i > 0) sb.append(',');
                write(sb, a[i]);
            }
            sb.append(']');
        } else if (o instanceof Character) {
            str(sb, o.toString());
        } else {
            str(sb, String.valueOf(o));
        }
    }

    private static void dbl(StringBuilder sb, double d) {
        if (Double.isNaN(d) || Double.isInfinite(d)) {
            str(sb, Double.toString(d));
        } else if (d == Math.rint(d) && Math.abs(d) < 1e15) {
            sb.append((long) d).append(".0");
        } else {
            sb.append(Double.toString(d));
        }
    }

    public static void str(StringBuilder sb, String s) {
        sb.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                case '\b': sb.append("\\b"); break;
                case '\f': sb.append("\\f"); break;
                default:
                    if (c < 0x20 || c == 0x2028 || c == 0x2029) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
            }
        }
        sb.append('"');
    }
}
