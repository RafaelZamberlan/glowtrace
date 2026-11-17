package io.glowtrace.agent.analysis;

import com.github.javaparser.ast.expr.AnnotationExpr;
import com.github.javaparser.ast.expr.ArrayInitializerExpr;
import com.github.javaparser.ast.expr.BinaryExpr;
import com.github.javaparser.ast.expr.EnclosedExpr;
import com.github.javaparser.ast.expr.Expression;
import com.github.javaparser.ast.expr.FieldAccessExpr;
import com.github.javaparser.ast.expr.MemberValuePair;
import com.github.javaparser.ast.expr.NameExpr;
import com.github.javaparser.ast.expr.NormalAnnotationExpr;
import com.github.javaparser.ast.expr.SingleMemberAnnotationExpr;
import com.github.javaparser.ast.expr.StringLiteralExpr;
import com.github.javaparser.ast.expr.TextBlockLiteralExpr;
import com.github.javaparser.ast.nodeTypes.NodeWithAnnotations;
import io.glowtrace.agent.analysis.ProjectIndex.FieldInfo;
import io.glowtrace.agent.analysis.ProjectIndex.MethodDef;
import io.glowtrace.agent.analysis.ProjectIndex.TypeInfo;
import io.glowtrace.agent.analysis.ProjectIndex.TypeRef;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Spring MVC endpoint discovery (@RestController/@Controller + mapping annotations, incl. inherited ones). */
final class RouteScanner {
    private static final Set<String> MAPPINGS = Set.of("GetMapping", "PostMapping", "PutMapping", "DeleteMapping",
            "PatchMapping", "RequestMapping");
    private static final Pattern PLACEHOLDER = Pattern.compile("\\$\\{[^}:]*(?::([^}]*))?}");
    private static final Set<String> FILTER_SUPERS = Set.of("OncePerRequestFilter", "GenericFilterBean", "Filter",
            "HttpFilter", "HandlerInterceptor", "AsyncHandlerInterceptor", "HandlerInterceptorAdapter");

    /** A discovered endpoint plus the pattern used to match requests at runtime. */
    static final class Route {
        final Map<String, Object> json;
        final List<String> methods;
        final String path;
        final Pattern regex;

        Route(Map<String, Object> json, List<String> methods, String path) {
            this.json = json;
            this.methods = methods;
            this.path = path;
            this.regex = toRegex(path);
        }

        String id() {
            return (String) json.get("id");
        }
    }

    private final ProjectIndex idx;

    RouteScanner(ProjectIndex idx) {
        this.idx = idx;
    }

    static String simple(AnnotationExpr a) {
        String n = a.getNameAsString();
        int dot = n.lastIndexOf('.');
        return dot >= 0 ? n.substring(dot + 1) : n;
    }

    static AnnotationExpr find(NodeWithAnnotations<?> n, String... names) {
        for (AnnotationExpr a : n.getAnnotations()) {
            String s = simple(a);
            for (String x : names) if (s.equals(x)) return a;
        }
        return null;
    }

    List<Route> scan() {
        List<Route> out = new ArrayList<>();
        Set<String> ids = new HashSet<>();
        for (TypeInfo t : idx.types) {
            if (t.isInterface || t.isAbstract) continue;
            if (find(t.decl, "RestController", "Controller") == null) continue;
            // class-level prefix: the controller's own @RequestMapping wins, else the first supertype's
            AnnotationExpr classMap = null;
            TypeInfo classMapOwner = null;
            for (TypeInfo x : idx.hierarchy(t)) {
                AnnotationExpr a = find(x.decl, "RequestMapping");
                if (a != null) {
                    classMap = a;
                    classMapOwner = x;
                    break;
                }
            }
            List<String> prefixes = classMap != null ? paths(classMap, classMapOwner) : List.of("");
            List<String> classMethods = classMap != null ? httpMethods(classMap) : List.of();
            Map<String, MethodDef> visible = new LinkedHashMap<>();
            for (TypeInfo x : idx.hierarchy(t)) {
                for (MethodDef m : x.methods) visible.putIfAbsent(m.name + "#" + m.paramCount, m);
            }
            for (MethodDef impl : visible.values()) {
                if (ProjectIndex.isStatic(impl.decl)) continue;
                AnnotationExpr mapping = null;
                MethodDef mappedOn = null;
                for (TypeInfo x : idx.hierarchy(t)) {
                    for (MethodDef m : x.methods) {
                        if (!m.name.equals(impl.name) || m.paramCount != impl.paramCount) continue;
                        AnnotationExpr a = mappingOf(m);
                        if (a != null) {
                            mapping = a;
                            mappedOn = m;
                            break;
                        }
                    }
                    if (mapping != null) break;
                }
                if (mapping == null) continue;
                List<String> methods = httpMethods(mapping);
                if (methods.isEmpty()) methods = classMethods;
                if (methods.isEmpty()) methods = List.of("ANY");
                List<String> paths = paths(mapping, mappedOn.owner);
                String summary = null;
                List<String> tags = new ArrayList<>();
                for (MethodDef m : new MethodDef[] {impl, mappedOn}) {
                    AnnotationExpr op = find(m.decl, "Operation");
                    if (op != null) {
                        if (summary == null) summary = constAttr(op, "summary", m.owner);
                        if (tags.isEmpty()) tags.addAll(constList(op, "tags", m.owner));
                    }
                }
                if (tags.isEmpty()) {
                    for (TypeInfo x : idx.hierarchy(t)) {
                        AnnotationExpr tag = find(x.decl, "Tag");
                        if (tag != null) {
                            String n = constAttr(tag, "name", x);
                            if (n != null) {
                                tags.add(n);
                                break;
                            }
                        }
                    }
                }
                for (String prefix : prefixes) {
                    for (String p : paths) {
                        String path = joinPath(prefix, p);
                        String base = String.join("|", methods) + " " + path;
                        String id = base;
                        int n = 2;
                        while (ids.contains(id)) id = base + " #" + n++;
                        ids.add(id);
                        Map<String, Object> r = new LinkedHashMap<>();
                        r.put("id", id);
                        r.put("kind", "http");
                        r.put("methods", methods);
                        r.put("path", path);
                        r.put("name", impl.name);
                        r.put("summary", summary);
                        r.put("tags", tags);
                        r.put("handler", impl.hasBody ? impl.fnId : null);
                        r.put("handler_desc", t.fqn + "." + impl.name);
                        r.put("dependencies", new ArrayList<>());
                        r.put("file", impl.owner.file.rel);
                        r.put("line", impl.decl.getName().getBegin().map(pos -> pos.line).orElse(0));
                        r.put("is_async", false);
                        String bodyParam = requestBodyParam(impl, mappedOn);
                        if (bodyParam != null) r.put("body_param", bodyParam);
                        out.add(new Route(r, methods, path));
                    }
                }
            }
        }
        return out;
    }

    /**
     * Name (in the implementation) of the parameter annotated with @RequestBody. The annotation may live on
     * the implementation or on the interface that declares the mapping (OpenAPI-generated APIs), so match by
     * position and report the implementation's parameter name - that is the key used in the frame's args.
     */
    static String requestBodyParam(MethodDef impl, MethodDef mappedOn) {
        for (MethodDef m : new MethodDef[] {impl, mappedOn}) {
            if (m == null) continue;
            var ps = m.decl.getParameters();
            for (int i = 0; i < ps.size() && i < impl.decl.getParameters().size(); i++) {
                for (AnnotationExpr a : ps.get(i).getAnnotations()) {
                    String n = a.getNameAsString();
                    if (n.equals("RequestBody") || n.endsWith(".RequestBody")) {
                        return impl.decl.getParameter(i).getNameAsString();
                    }
                }
            }
        }
        return null;
    }

    List<Map<String, Object>> middlewares() {
        List<Map<String, Object>> out = new ArrayList<>();
        for (TypeInfo t : idx.types) {
            if (t.isInterface || t.isAbstract) continue;
            boolean filter = false;
            for (String e : idx.allExternalSupers(t)) {
                String s = e.substring(e.lastIndexOf('.') + 1);
                if (FILTER_SUPERS.contains(s)) {
                    filter = true;
                    break;
                }
            }
            if (!filter) continue;
            String fn = null;
            for (String name : new String[] {"doFilterInternal", "doFilter", "preHandle"}) {
                for (MethodDef m : t.methods) {
                    if (m.name.equals(name) && m.hasBody) {
                        fn = m.fnId;
                        break;
                    }
                }
                if (fn != null) break;
            }
            Map<String, Object> mw = new LinkedHashMap<>();
            mw.put("name", t.simpleName);
            mw.put("fn", fn);
            mw.put("kind", fn != null ? "user" : "library");
            out.add(mw);
        }
        return out;
    }

    private static AnnotationExpr mappingOf(MethodDef m) {
        for (AnnotationExpr a : m.decl.getAnnotations()) {
            if (MAPPINGS.contains(simple(a))) return a;
        }
        return null;
    }

    private static List<String> httpMethods(AnnotationExpr a) {
        String s = simple(a);
        switch (s) {
            case "GetMapping": return List.of("GET");
            case "PostMapping": return List.of("POST");
            case "PutMapping": return List.of("PUT");
            case "DeleteMapping": return List.of("DELETE");
            case "PatchMapping": return List.of("PATCH");
            default: break;
        }
        Expression v = attr(a, "method");
        if (v == null) return List.of();
        TreeSet<String> out = new TreeSet<>();
        List<Expression> items = new ArrayList<>();
        if (v instanceof ArrayInitializerExpr) items.addAll(((ArrayInitializerExpr) v).getValues());
        else items.add(v);
        for (Expression e : items) {
            String t = e.toString();
            out.add(t.substring(t.lastIndexOf('.') + 1).toUpperCase());
        }
        return new ArrayList<>(out);
    }

    private static Expression attr(AnnotationExpr a, String... names) {
        if (a instanceof SingleMemberAnnotationExpr) {
            for (String n : names) if (n.equals("value")) return ((SingleMemberAnnotationExpr) a).getMemberValue();
            return null;
        }
        if (a instanceof NormalAnnotationExpr) {
            for (String n : names) {
                for (MemberValuePair p : ((NormalAnnotationExpr) a).getPairs()) {
                    if (p.getNameAsString().equals(n)) return p.getValue();
                }
            }
        }
        return null;
    }

    private List<String> paths(AnnotationExpr a, TypeInfo ctx) {
        Expression v = attr(a, "value", "path");
        if (v == null) return List.of("");
        List<String> out = new ArrayList<>();
        if (v instanceof ArrayInitializerExpr) {
            for (Expression e : ((ArrayInitializerExpr) v).getValues()) out.add(placeholders(constOrText(e, ctx)));
        } else {
            out.add(placeholders(constOrText(v, ctx)));
        }
        if (out.isEmpty()) out.add("");
        return out;
    }

    private String constAttr(AnnotationExpr a, String name, TypeInfo ctx) {
        Expression v = attr(a, name);
        return v == null ? null : constOrText(v, ctx);
    }

    private List<String> constList(AnnotationExpr a, String name, TypeInfo ctx) {
        Expression v = attr(a, name);
        List<String> out = new ArrayList<>();
        if (v == null) return out;
        if (v instanceof ArrayInitializerExpr) {
            for (Expression e : ((ArrayInitializerExpr) v).getValues()) out.add(constOrText(e, ctx));
        } else {
            out.add(constOrText(v, ctx));
        }
        return out;
    }

    private String constOrText(Expression e, TypeInfo ctx) {
        String s = constString(e, ctx, 0);
        return s != null ? s : e.toString();
    }

    /** Evaluates string constants: literals, concatenation, (Type.)CONSTANT fields of project types. */
    String constString(Expression e, TypeInfo ctx, int depth) {
        if (e == null || depth > 8) return null;
        if (e instanceof StringLiteralExpr) return ((StringLiteralExpr) e).asString();
        if (e instanceof TextBlockLiteralExpr) return ((TextBlockLiteralExpr) e).asString();
        if (e instanceof EnclosedExpr) return constString(((EnclosedExpr) e).getInner(), ctx, depth + 1);
        if (e instanceof BinaryExpr && ((BinaryExpr) e).getOperator() == BinaryExpr.Operator.PLUS) {
            String l = constString(((BinaryExpr) e).getLeft(), ctx, depth + 1);
            String r = constString(((BinaryExpr) e).getRight(), ctx, depth + 1);
            return l != null && r != null ? l + r : null;
        }
        if (e instanceof NameExpr) {
            String n = ((NameExpr) e).getNameAsString();
            for (TypeInfo t = ctx; t != null; t = t.outer) {
                FieldInfo f = idx.findField(t, n);
                if (f != null && f.init != null) return constString(f.init, f.owner, depth + 1);
            }
            if (ctx != null) {
                String cls = ctx.file.staticImports.get(n);
                if (cls != null) {
                    TypeRef r = idx.resolve(cls, ctx, ctx.file);
                    if (r != null && r.type != null) {
                        FieldInfo f = idx.findField(r.type, n);
                        if (f != null && f.init != null) return constString(f.init, f.owner, depth + 1);
                    }
                }
            }
            return null;
        }
        if (e instanceof FieldAccessExpr && ctx != null) {
            FieldAccessExpr fa = (FieldAccessExpr) e;
            TypeRef r = idx.resolve(fa.getScope().toString(), ctx, ctx.file);
            if (r != null && r.type != null) {
                FieldInfo f = idx.findField(r.type, fa.getNameAsString());
                if (f != null && f.init != null) return constString(f.init, f.owner, depth + 1);
            }
        }
        return null;
    }

    private static String placeholders(String s) {
        if (s == null || !s.contains("${")) return s;
        Matcher m = PLACEHOLDER.matcher(s);
        StringBuilder sb = new StringBuilder();
        while (m.find()) m.appendReplacement(sb, Matcher.quoteReplacement(m.group(1) != null ? m.group(1) : ""));
        m.appendTail(sb);
        return sb.toString();
    }

    static String joinPath(String a, String b) {
        String s = (a == null ? "" : a.trim()) + "/" + (b == null ? "" : b.trim());
        s = s.replaceAll("/+", "/");
        if (!s.startsWith("/")) s = "/" + s;
        if (s.length() > 1 && s.endsWith("/")) s = s.substring(0, s.length() - 1);
        return s;
    }

    /** "/owners/{id}/pets/**" -> regex used when the framework did not tell us the matched pattern. */
    static Pattern toRegex(String path) {
        StringBuilder sb = new StringBuilder("^");
        int i = 0;
        while (i < path.length()) {
            char c = path.charAt(i);
            if (c == '{') {
                int depth = 1;
                int j = i + 1;
                while (j < path.length() && depth > 0) {
                    if (path.charAt(j) == '{') depth++;
                    else if (path.charAt(j) == '}') depth--;
                    j++;
                }
                String inner = path.substring(i + 1, Math.max(i + 1, j - 1));
                sb.append(inner.startsWith("*") ? ".*" : "[^/]+");
                i = j;
            } else if (path.startsWith("**", i)) {
                sb.append(".*");
                i += 2;
            } else if (c == '*') {
                sb.append("[^/]*");
                i++;
            } else {
                sb.append(Pattern.quote(String.valueOf(c)));
                i++;
            }
        }
        sb.append("/?$");
        try {
            return Pattern.compile(sb.toString());
        } catch (Exception e) {
            return Pattern.compile("^" + Pattern.quote(path) + "$");
        }
    }
}
