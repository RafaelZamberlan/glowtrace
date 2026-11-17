package io.glowtrace.agent.analysis;

import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.Parameter;
import com.github.javaparser.ast.body.VariableDeclarator;
import com.github.javaparser.ast.expr.CastExpr;
import com.github.javaparser.ast.expr.EnclosedExpr;
import com.github.javaparser.ast.expr.Expression;
import com.github.javaparser.ast.expr.FieldAccessExpr;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.expr.NameExpr;
import com.github.javaparser.ast.expr.ObjectCreationExpr;
import com.github.javaparser.ast.expr.StringLiteralExpr;
import com.github.javaparser.ast.expr.SuperExpr;
import com.github.javaparser.ast.expr.TextBlockLiteralExpr;
import com.github.javaparser.ast.expr.ThisExpr;
import com.github.javaparser.ast.expr.TypePatternExpr;
import com.github.javaparser.ast.type.ClassOrInterfaceType;
import com.github.javaparser.ast.type.Type;
import com.github.javaparser.ast.type.UnknownType;
import io.glowtrace.agent.analysis.ProjectIndex.FieldInfo;
import io.glowtrace.agent.analysis.ProjectIndex.MethodDef;
import io.glowtrace.agent.analysis.ProjectIndex.SourceFile;
import io.glowtrace.agent.analysis.ProjectIndex.TypeInfo;
import io.glowtrace.agent.analysis.ProjectIndex.TypeRef;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/** Classifies method calls: user (project method), external (library / I/O), stdlib, builtin, unresolved. */
final class CallResolver {

    static final class Local {
        final Type type;
        final Expression init;

        Local(Type type, Expression init) {
            this.type = type;
            this.init = init;
        }
    }

    /** Names visible inside one method body (shadowing ignored). */
    static final class Scope {
        final TypeInfo type;
        final SourceFile sf;
        final Map<String, Local> locals = new HashMap<>();

        Scope(TypeInfo type, MethodDef m) {
            this.type = type;
            this.sf = type.file;
            for (Parameter p : m.decl.getParameters()) locals.put(p.getNameAsString(), new Local(p.getType(), null));
            m.decl.getBody().ifPresent(b -> collect(b));
        }

        private void collect(Node n) {
            if (n instanceof VariableDeclarator) {
                VariableDeclarator v = (VariableDeclarator) n;
                locals.putIfAbsent(v.getNameAsString(), new Local(v.getType(), v.getInitializer().orElse(null)));
            } else if (n instanceof Parameter) {
                Parameter p = (Parameter) n;
                if (!(p.getType() instanceof UnknownType)) {
                    locals.putIfAbsent(p.getNameAsString(), new Local(p.getType(), null));
                }
            } else if (n instanceof TypePatternExpr) {
                TypePatternExpr tp = (TypePatternExpr) n;
                locals.putIfAbsent(tp.getNameAsString(), new Local(tp.getType(), null));
            } else if (n instanceof ClassOrInterfaceDeclaration) {
                return; // local classes have their own scope
            }
            for (Node c : n.getChildNodes()) collect(c);
        }
    }

    private final ProjectIndex idx;

    CallResolver(ProjectIndex idx) {
        this.idx = idx;
    }

    static String exprText(MethodCallExpr call) {
        String scope = call.getScope().map(Node::toString).orElse(null);
        if (scope != null) {
            scope = scope.replaceAll("\\s+", " ");
            if (scope.length() > 60) scope = scope.substring(0, 59) + "…";
        }
        return scope == null ? call.getNameAsString() : scope + "." + call.getNameAsString();
    }

    Flow.CallInfo classify(MethodCallExpr call, Scope sc) {
        String expr = exprText(call);
        try {
            return classify0(call, sc, expr);
        } catch (RuntimeException e) {
            return new Flow.CallInfo(expr, "unresolved", null, null);
        }
    }

    private Flow.CallInfo classify0(MethodCallExpr call, Scope sc, String expr) {
        String name = call.getNameAsString();
        int argc = call.getArguments().size();
        Optional<Expression> scopeOpt = call.getScope();
        if (scopeOpt.isEmpty() || scopeOpt.get() instanceof ThisExpr) {
            for (TypeInfo t = sc.type; t != null; t = t.outer) {
                MethodDef m = idx.findMethod(t, name, argc);
                if (m != null) return userCall(expr, m, t);
                if (scopeOpt.isPresent()) break;
            }
            String cls = sc.sf.staticImports.get(name);
            if (cls != null) return byType(expr, idx.resolve(cls, sc.type, sc.sf), name, argc);
            for (String w : sc.sf.staticWildcards) {
                TypeInfo t = idx.type(w);
                if (t != null) {
                    MethodDef m = idx.findMethod(t, name, argc);
                    if (m != null) return userCall(expr, m, t);
                }
            }
            List<String> ext = idx.allExternalSupers(sc.type);
            if (!ext.isEmpty()) return external(expr, ext.get(0));
            if (!sc.sf.staticWildcards.isEmpty()) return external(expr, sc.sf.staticWildcards.get(0));
            return unresolved(expr);
        }
        Expression scope = scopeOpt.get();
        if (scope instanceof SuperExpr) {
            for (TypeInfo s : sc.type.supers) {
                MethodDef m = idx.findMethod(s, name, argc);
                if (m != null) return userCall(expr, m, s);
            }
            List<String> ext = idx.allExternalSupers(sc.type);
            if (!ext.isEmpty()) return external(expr, ext.get(0));
            return unresolved(expr);
        }
        TypeRef t = typeOf(scope, sc, 0);
        if (t == null) return unresolved(expr);
        return byType(expr, t, name, argc);
    }

    private Flow.CallInfo byType(String expr, TypeRef t, String name, int argc) {
        if (t == null) return unresolved(expr);
        if (t.type != null) {
            MethodDef m = idx.findMethod(t.type, name, argc);
            if (m != null) return userCall(expr, m, t.type);
            List<String> ext = idx.allExternalSupers(t.type);
            if (!ext.isEmpty()) return external(expr, ext.get(0));
            if (t.type.decl instanceof com.github.javaparser.ast.body.EnumDeclaration
                    || t.type.decl instanceof com.github.javaparser.ast.body.RecordDeclaration) {
                return new Flow.CallInfo(expr, "builtin", null, null); // values(), valueOf(), accessors
            }
            return unresolved(expr);
        }
        return external(expr, t.external);
    }

    private Flow.CallInfo userCall(String expr, MethodDef m, TypeInfo staticType) {
        if (m.trivial) return new Flow.CallInfo(expr, "builtin", null, null);
        if (!m.hasBody) {
            if (idx.isSpringData(staticType) || idx.isSpringData(m.owner)) {
                return new Flow.CallInfo(expr, "external", null, "spring");
            }
            MethodDef impl = idx.uniqueImplementation(m, staticType);
            if (impl != null) {
                if (impl.trivial) return new Flow.CallInfo(expr, "builtin", null, null);
                return new Flow.CallInfo(expr, "user", impl.fnId, null);
            }
        }
        return new Flow.CallInfo(expr, "user", m.fnId, null);
    }

    private static Flow.CallInfo unresolved(String expr) {
        return new Flow.CallInfo(expr, "unresolved", null, null);
    }

    static Flow.CallInfo external(String expr, String fqn) {
        String[] kl = classifyFqn(fqn);
        return new Flow.CallInfo(expr, kl[0], null, kl[1]);
    }

    /** {kind, lib} for a non-project type FQN. */
    static String[] classifyFqn(String fqn) {
        if (fqn == null || fqn.isEmpty()) return new String[] {"unresolved", null};
        String[] seg = fqn.split("\\.");
        if (fqn.startsWith("java.lang.") && seg.length == 3) return new String[] {"builtin", null};
        if (fqn.startsWith("java.util.logging.") || fqn.startsWith("org.slf4j.") || fqn.startsWith("ch.qos.logback.")
                || fqn.startsWith("org.apache.logging.") || fqn.startsWith("org.apache.commons.logging.")
                || fqn.startsWith("lombok.")) {
            return new String[] {"stdlib", "logging"};
        }
        if (fqn.startsWith("java.io.") || fqn.startsWith("java.nio.") || fqn.startsWith("java.net.")
                || fqn.startsWith("java.sql.") || fqn.startsWith("javax.sql.")) {
            return new String[] {"external", seg[0] + "." + seg[1]};
        }
        if (fqn.startsWith("java.") || fqn.startsWith("jdk.")) return new String[] {"stdlib", "java"};
        if (fqn.startsWith("javax.")) {
            String s = seg.length > 1 ? seg[1] : "";
            if (s.equals("persistence") || s.equals("servlet") || s.equals("validation") || s.equals("ws")
                    || s.equals("inject") || s.equals("ejb") || s.equals("transaction") || s.equals("jms")
                    || s.equals("mail")) {
                return new String[] {"external", "javax"};
            }
            return new String[] {"stdlib", "javax"};
        }
        return new String[] {"external", libOf(fqn)};
    }

    static String libOf(String fqn) {
        String[] seg = fqn.split("\\.");
        if (fqn.startsWith("org.springframework")) return "spring";
        if (fqn.startsWith("com.fasterxml.jackson")) return "jackson";
        if (seg.length >= 2) {
            switch (seg[0]) {
                case "org": case "com": case "io": case "net": case "dev": case "me": case "ch": case "de": case "fr":
                case "br": case "uk": case "edu": case "info":
                    return seg[1];
                default:
                    return seg[0];
            }
        }
        return seg[0];
    }

    // ------------------------------------------------------------------ expression types

    TypeRef typeOf(Expression e, Scope sc, int depth) {
        if (e == null || depth > 5) return null;
        if (e instanceof EnclosedExpr) return typeOf(((EnclosedExpr) e).getInner(), sc, depth + 1);
        if (e instanceof ThisExpr) return ProjectIndex.ref(sc.type);
        if (e instanceof StringLiteralExpr || e instanceof TextBlockLiteralExpr) return ProjectIndex.ext("java.lang.String");
        if (e instanceof CastExpr) return typeRef(((CastExpr) e).getType(), sc.type, sc.sf);
        if (e instanceof ObjectCreationExpr) return typeRef(((ObjectCreationExpr) e).getType(), sc.type, sc.sf);
        if (e instanceof NameExpr) {
            String n = ((NameExpr) e).getNameAsString();
            Local l = sc.locals.get(n);
            if (l != null) {
                TypeRef r = typeRef(l.type, sc.type, sc.sf);
                if (r == null && l.init != null && (l.type == null || l.type.isVarType())) {
                    r = typeOf(l.init, sc, depth + 1);
                }
                return r;
            }
            for (TypeInfo t = sc.type; t != null; t = t.outer) {
                FieldInfo f = idx.findField(t, n);
                if (f != null) return typeRef(f.type, f.owner, f.owner.file);
            }
            if (!n.isEmpty() && Character.isUpperCase(n.charAt(0))) return idx.resolve(n, sc.type, sc.sf);
            return null;
        }
        if (e instanceof FieldAccessExpr) {
            FieldAccessExpr fa = (FieldAccessExpr) e;
            String n = fa.getNameAsString();
            if (fa.getScope() instanceof ThisExpr) {
                FieldInfo f = idx.findField(sc.type, n);
                return f == null ? null : typeRef(f.type, f.owner, f.owner.file);
            }
            if (!n.isEmpty() && Character.isUpperCase(n.charAt(0)) && looksQualified(fa)) {
                TypeRef r = idx.resolve(fa.toString(), sc.type, sc.sf);
                if (r != null) return r;
            }
            TypeRef st = typeOf(fa.getScope(), sc, depth + 1);
            if (st != null && st.type != null) {
                FieldInfo f = idx.findField(st.type, n);
                if (f != null) return typeRef(f.type, f.owner, f.owner.file);
            }
            return null;
        }
        if (e instanceof MethodCallExpr) {
            MethodDef m = resolveMethod((MethodCallExpr) e, sc, depth + 1);
            if (m != null) return typeRef(m.decl.getType(), m.owner, m.owner.file);
            return null;
        }
        return null;
    }

    private static boolean looksQualified(FieldAccessExpr fa) {
        Expression s = fa.getScope();
        while (s instanceof FieldAccessExpr) s = ((FieldAccessExpr) s).getScope();
        return s instanceof NameExpr;
    }

    private MethodDef resolveMethod(MethodCallExpr call, Scope sc, int depth) {
        String name = call.getNameAsString();
        int argc = call.getArguments().size();
        Optional<Expression> scopeOpt = call.getScope();
        if (scopeOpt.isEmpty() || scopeOpt.get() instanceof ThisExpr) {
            for (TypeInfo t = sc.type; t != null; t = t.outer) {
                MethodDef m = idx.findMethod(t, name, argc);
                if (m != null) return m;
            }
            return null;
        }
        TypeRef t = typeOf(scopeOpt.get(), sc, depth);
        if (t == null || t.type == null) return null;
        return idx.findMethod(t.type, name, argc);
    }

    TypeRef typeRef(Type type, TypeInfo ctx, SourceFile sf) {
        if (type == null) return null;
        if (type instanceof ClassOrInterfaceType) {
            return idx.resolve(((ClassOrInterfaceType) type).getNameWithScope(), ctx, sf);
        }
        return null;
    }
}
