package io.glowtrace.agent.runtime;

import java.lang.reflect.Method;
import java.util.Collection;
import java.util.Enumeration;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/** Reflection access to jakarta.servlet / javax.servlet request & response (no compile-time dependency). */
final class ServletBridge {
    private ServletBridge() {}

    static final class Api {
        final Method getMethod, getRequestURI, getQueryString, getContextPath, getHeaderNames, getHeader,
                getAttribute, getDispatcherType;
        final Method getStatus, respHeaderNames, respHeader, setHeader;

        Api(Class<?> req, Class<?> resp) throws ReflectiveOperationException {
            getMethod = req.getMethod("getMethod");
            getRequestURI = req.getMethod("getRequestURI");
            getQueryString = req.getMethod("getQueryString");
            getContextPath = req.getMethod("getContextPath");
            getHeaderNames = req.getMethod("getHeaderNames");
            getHeader = req.getMethod("getHeader", String.class);
            getAttribute = req.getMethod("getAttribute", String.class);
            getDispatcherType = req.getMethod("getDispatcherType");
            getStatus = resp.getMethod("getStatus");
            respHeaderNames = resp.getMethod("getHeaderNames");
            respHeader = resp.getMethod("getHeader", String.class);
            setHeader = resp.getMethod("setHeader", String.class, String.class);
        }

        String method(Object req) {
            return (String) call(getMethod, req);
        }

        String uri(Object req) {
            return (String) call(getRequestURI, req);
        }

        String query(Object req) {
            return (String) call(getQueryString, req);
        }

        String contextPath(Object req) {
            Object o = call(getContextPath, req);
            return o == null ? "" : (String) o;
        }

        String header(Object req, String name) {
            return (String) call(getHeader, req, name);
        }

        Object attribute(Object req, String name) {
            return call(getAttribute, req, name);
        }

        boolean isRequestDispatch(Object req) {
            Object t = call(getDispatcherType, req);
            return t == null || "REQUEST".equals(((Enum<?>) t).name());
        }

        Map<String, String> headers(Object req) {
            Map<String, String> out = new LinkedHashMap<>();
            Object names = call(getHeaderNames, req);
            if (names instanceof Enumeration) {
                Enumeration<?> e = (Enumeration<?>) names;
                int n = 0;
                while (e.hasMoreElements() && n++ < 100) {
                    String k = String.valueOf(e.nextElement());
                    out.put(k.toLowerCase(), header(req, k));
                }
            }
            return out;
        }

        int status(Object resp) {
            Object o = call(getStatus, resp);
            return o instanceof Integer ? (Integer) o : 0;
        }

        Map<String, String> responseHeaders(Object resp) {
            Map<String, String> out = new LinkedHashMap<>();
            Object names = call(respHeaderNames, resp);
            if (names instanceof Collection) {
                int n = 0;
                for (Object k : (Collection<?>) names) {
                    if (n++ >= 100) break;
                    String key = String.valueOf(k);
                    out.put(key.toLowerCase(), (String) call(respHeader, resp, key));
                }
            }
            return out;
        }

        void setHeader(Object resp, String name, String value) {
            call(setHeader, resp, name, value);
        }

        private static Object call(Method m, Object target, Object... args) {
            try {
                return m.invoke(target, args);
            } catch (Throwable t) {
                return null;
            }
        }
    }

    private static final Object NONE = new Object();
    private static final ConcurrentHashMap<Class<?>, Object> CACHE = new ConcurrentHashMap<>();

    static Api api(Object req) {
        if (req == null) return null;
        Object a = CACHE.computeIfAbsent(req.getClass(), ServletBridge::build);
        return a == NONE ? null : (Api) a;
    }

    private static Object build(Class<?> c) {
        for (String base : new String[] {"jakarta.servlet.http", "javax.servlet.http"}) {
            try {
                Class<?> req = Class.forName(base + ".HttpServletRequest", false, c.getClassLoader());
                if (!req.isAssignableFrom(c)) continue;
                Class<?> resp = Class.forName(base + ".HttpServletResponse", false, req.getClassLoader());
                return new Api(req, resp);
            } catch (Throwable ignored) {
                // try the next servlet flavour
            }
        }
        return NONE;
    }
}
