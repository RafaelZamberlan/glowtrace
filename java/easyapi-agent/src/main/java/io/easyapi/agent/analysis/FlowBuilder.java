package io.easyapi.agent.analysis;

import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.NodeList;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.Parameter;
import com.github.javaparser.ast.body.TypeDeclaration;
import com.github.javaparser.ast.body.VariableDeclarator;
import com.github.javaparser.ast.expr.ArrayAccessExpr;
import com.github.javaparser.ast.expr.AssignExpr;
import com.github.javaparser.ast.expr.BooleanLiteralExpr;
import com.github.javaparser.ast.expr.Expression;
import com.github.javaparser.ast.expr.FieldAccessExpr;
import com.github.javaparser.ast.expr.LambdaExpr;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.expr.MethodReferenceExpr;
import com.github.javaparser.ast.expr.NameExpr;
import com.github.javaparser.ast.expr.ObjectCreationExpr;
import com.github.javaparser.ast.expr.UnaryExpr;
import com.github.javaparser.ast.expr.VariableDeclarationExpr;
import com.github.javaparser.ast.stmt.AssertStmt;
import com.github.javaparser.ast.stmt.BlockStmt;
import com.github.javaparser.ast.stmt.BreakStmt;
import com.github.javaparser.ast.stmt.CatchClause;
import com.github.javaparser.ast.stmt.ContinueStmt;
import com.github.javaparser.ast.stmt.DoStmt;
import com.github.javaparser.ast.stmt.EmptyStmt;
import com.github.javaparser.ast.stmt.ExplicitConstructorInvocationStmt;
import com.github.javaparser.ast.stmt.ExpressionStmt;
import com.github.javaparser.ast.stmt.ForEachStmt;
import com.github.javaparser.ast.stmt.ForStmt;
import com.github.javaparser.ast.stmt.IfStmt;
import com.github.javaparser.ast.stmt.LabeledStmt;
import com.github.javaparser.ast.stmt.LocalClassDeclarationStmt;
import com.github.javaparser.ast.stmt.LocalRecordDeclarationStmt;
import com.github.javaparser.ast.stmt.ReturnStmt;
import com.github.javaparser.ast.stmt.Statement;
import com.github.javaparser.ast.stmt.SwitchEntry;
import com.github.javaparser.ast.stmt.SwitchStmt;
import com.github.javaparser.ast.stmt.SynchronizedStmt;
import com.github.javaparser.ast.stmt.ThrowStmt;
import com.github.javaparser.ast.stmt.TryStmt;
import com.github.javaparser.ast.stmt.WhileStmt;
import io.easyapi.agent.analysis.ProjectIndex.MethodDef;
import io.easyapi.agent.analysis.ProjectIndex.SourceFile;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.Iterator;
import java.util.List;

/**
 * Java method body -> human-readable flow graph, mirroring python/src/easyapi/static/flow.py:
 * consecutive boring statements become one {@code step}; statements calling project code / libraries
 * become {@code call}; control structures get their own nodes and labelled edges.
 */
final class FlowBuilder {
    private static final int MAX_GROUP = 8;
    private static final int LABEL_MAX = 90;

    private static final class Pred {
        final int src;
        final String kind;
        final String label;

        Pred(int src, String kind, String label) {
            this.src = src;
            this.kind = kind;
            this.label = label;
        }
    }

    private static final class Breakable {
        final boolean loop;
        final int head;
        final String label;
        final List<Pred> breaks = new ArrayList<>();

        Breakable(boolean loop, int head, String label) {
            this.loop = loop;
            this.head = head;
            this.label = label;
        }
    }

    private final MethodDef m;
    private final SourceFile sf;
    private final CallResolver resolver;
    private final CallResolver.Scope scope;
    private final List<Flow.Node> nodes = new ArrayList<>();
    private final List<Flow.Edge> edges = new ArrayList<>();
    private final Deque<Breakable> breakables = new ArrayDeque<>();
    private final Deque<Integer> trys = new ArrayDeque<>();
    private final Deque<List<Integer>> handlers = new ArrayDeque<>();
    private final List<Integer> returns = new ArrayList<>();
    private String pendingLabel;

    FlowBuilder(MethodDef m, CallResolver resolver) {
        this.m = m;
        this.sf = m.owner.file;
        this.resolver = resolver;
        this.scope = new CallResolver.Scope(m.owner, m);
    }

    // ------------------------------------------------------------------ entry

    Flow build() {
        MethodDeclaration d = m.decl;
        int nameLine = d.getName().getBegin().map(p -> p.line).orElse(begin(d));
        String sig;
        try {
            StringBuilder sb = new StringBuilder();
            sb.append(d.getType().asString()).append(' ').append(d.getNameAsString()).append('(');
            for (int i = 0; i < d.getParameters().size(); i++) {
                Parameter p = d.getParameter(i);
                if (i > 0) sb.append(", ");
                sb.append(p.getType().asString()).append(p.isVarArgs() ? "... " : " ").append(p.getNameAsString());
            }
            sig = sb.append(')').toString();
        } catch (RuntimeException e) {
            sig = d.getNameAsString() + "(…)";
        }
        Flow.Node start = add("start", sig, nameLine, nameLine);
        List<Pred> outs = one(start.idx, "next", "");
        if (d.getBody().isPresent()) outs = block(d.getBody().get().getStatements(), outs);
        int endLine = end(d);
        Flow.Node endNode = add("end", "fim", endLine, endLine);
        link(outs, endNode.idx);
        for (int r : returns) edges.add(new Flow.Edge(r, endNode.idx, "return", ""));

        Flow f = new Flow();
        f.fnId = m.fnId;
        f.qualname = m.qualname;
        f.relFile = sf.rel;
        f.line = nameLine;
        f.endLine = endLine;
        for (Parameter p : d.getParameters()) f.params.add(p.getNameAsString());
        f.doc = d.getJavadoc().map(j -> j.getDescription().toText().trim()).filter(s -> !s.isEmpty()).orElse(null);
        f.sourceStart = begin(d);
        f.source = sf.lineRange(f.sourceStart, endLine);
        f.sourceHash = sha1(f.source).substring(0, 12);
        f.nodes = nodes;
        f.edges = edges;
        for (Flow.Node n : nodes) {
            for (int[] r : n.own) {
                for (int ln = r[0]; ln <= r[1]; ln++) f.lines.putIfAbsent(ln, n.idx);
            }
        }
        return f;
    }

    /** Minimal flow (start -> end) used when building the real one failed. */
    static Flow fallback(MethodDef m) {
        Flow f = new Flow();
        MethodDeclaration d = m.decl;
        int line = d.getName().getBegin().map(p -> p.line).orElse(1);
        int endLine = d.getEnd().map(p -> p.line).orElse(line);
        f.fnId = m.fnId;
        f.qualname = m.qualname;
        f.relFile = m.owner.file.rel;
        f.line = line;
        f.endLine = endLine;
        for (Parameter p : d.getParameters()) f.params.add(p.getNameAsString());
        f.sourceStart = d.getBegin().map(p -> p.line).orElse(line);
        f.source = m.owner.file.lineRange(f.sourceStart, endLine);
        f.sourceHash = sha1(f.source).substring(0, 12);
        Flow.Node s = new Flow.Node(0, "start", shorten(d.getNameAsString() + "(…)", LABEL_MAX), line, line);
        Flow.Node e = new Flow.Node(1, "end", "fim", endLine, endLine);
        f.nodes.add(s);
        f.nodes.add(e);
        f.edges.add(new Flow.Edge(0, 1, "next", ""));
        return f;
    }

    // ------------------------------------------------------------------ primitives

    private Flow.Node add(String kind, String label, int line, int endLine) {
        Flow.Node n = new Flow.Node(nodes.size(), kind, shorten(label, LABEL_MAX), line, endLine);
        n.tryParent = trys.isEmpty() ? null : trys.peek();
        n.loopParent = innermostLoop();
        nodes.add(n);
        return n;
    }

    private Integer innermostLoop() {
        for (Breakable b : breakables) if (b.loop) return b.head;
        return null;
    }

    private void link(List<Pred> preds, int target) {
        for (Pred p : preds) edges.add(new Flow.Edge(p.src, target, p.kind, p.label));
    }

    private static List<Pred> one(int src, String kind, String label) {
        List<Pred> l = new ArrayList<>();
        l.add(new Pred(src, kind, label));
        return l;
    }

    static String shorten(String text, int limit) {
        if (text == null) return "";
        String t = text.trim().replaceAll("\\s+", " ");
        return t.length() <= limit ? t : t.substring(0, limit - 1) + "…";
    }

    private static int begin(Node n) {
        return n.getBegin().map(p -> p.line).orElse(0);
    }

    private static int end(Node n) {
        return n.getEnd().map(p -> p.line).orElse(begin(n));
    }

    private String text(Node n) {
        return sf.text(n);
    }

    private static int[] range(int a, int b) {
        return new int[] {a, Math.max(a, b)};
    }

    /** First line of the first real statement of a body (-1 if empty). */
    private static int firstLine(Statement s) {
        if (s instanceof BlockStmt) {
            for (Statement x : ((BlockStmt) s).getStatements()) {
                if (x instanceof EmptyStmt) continue;
                int l = firstLine(x);
                if (l > 0) return l;
            }
            return -1;
        }
        return begin(s);
    }

    /** Header lines of a control structure: from its line to the line before the body's 1st statement. */
    private static int[] header(Node stmt, Statement body) {
        int start = begin(stmt);
        int fb = body == null ? -1 : firstLine(body);
        if (fb < 0) fb = start + 1;
        return range(start, fb - 1);
    }

    private static List<Statement> stmtsOf(Statement s) {
        if (s == null) return new ArrayList<>();
        if (s instanceof BlockStmt) return ((BlockStmt) s).getStatements();
        List<Statement> l = new ArrayList<>();
        l.add(s);
        return l;
    }

    private static List<Statement> expand(List<Statement> in) {
        List<Statement> out = new ArrayList<>();
        for (Statement s : in) {
            if (s instanceof BlockStmt) out.addAll(expand(((BlockStmt) s).getStatements()));
            else if (!(s instanceof EmptyStmt)) out.add(s);
        }
        return out;
    }

    private static boolean isSimple(Statement s) {
        return s instanceof ExpressionStmt || s instanceof AssertStmt || s instanceof ExplicitConstructorInvocationStmt;
    }

    // ------------------------------------------------------------------ calls / names

    private static void collectCalls(Node n, List<MethodCallExpr> out) {
        if (n instanceof LambdaExpr || n instanceof MethodReferenceExpr || n instanceof TypeDeclaration
                || n instanceof LocalClassDeclarationStmt || n instanceof LocalRecordDeclarationStmt) {
            return;
        }
        if (n instanceof ObjectCreationExpr) {
            ObjectCreationExpr oc = (ObjectCreationExpr) n;
            oc.getScope().ifPresent(s -> collectCalls(s, out));
            for (Expression a : oc.getArguments()) collectCalls(a, out);
            return;
        }
        if (n instanceof MethodCallExpr) out.add((MethodCallExpr) n);
        for (Node c : n.getChildNodes()) collectCalls(c, out);
    }

    private List<Flow.CallInfo> callsOf(Node n) {
        List<Flow.CallInfo> infos = new ArrayList<>();
        if (n == null) return infos;
        List<MethodCallExpr> calls = new ArrayList<>();
        collectCalls(n, calls);
        for (MethodCallExpr c : calls) {
            Flow.CallInfo info = resolver.classify(c, scope);
            info.line = begin(c);
            infos.add(info);
        }
        return infos;
    }

    private List<Flow.CallInfo> callsOf(List<? extends Node> ns) {
        List<Flow.CallInfo> out = new ArrayList<>();
        for (Node n : ns) out.addAll(callsOf(n));
        return out;
    }

    private static List<Flow.CallInfo> nonBuiltin(List<Flow.CallInfo> calls, int limit) {
        List<Flow.CallInfo> out = new ArrayList<>();
        for (Flow.CallInfo c : calls) {
            if (!"builtin".equals(c.kind) && out.size() < limit) out.add(c);
        }
        return out;
    }

    private static List<Flow.CallInfo> interesting(List<Flow.CallInfo> calls) {
        List<Flow.CallInfo> out = new ArrayList<>();
        for (Flow.CallInfo c : calls) if (c.interesting()) out.add(c);
        return out;
    }

    private static List<String> readNames(Node e, int limit) {
        List<String> seen = new ArrayList<>();
        if (e != null) readNames(e, seen, limit);
        return seen;
    }

    private static void readNames(Node n, List<String> seen, int limit) {
        if (seen.size() >= limit) return;
        if (n instanceof NameExpr) {
            String s = ((NameExpr) n).getNameAsString();
            // skip type names used as static scopes (Math.max, Boolean.TRUE); keep CONSTANTS and variables
            boolean typeName = s.length() > 1 && Character.isUpperCase(s.charAt(0)) && Character.isLowerCase(s.charAt(1));
            if (!typeName && !seen.contains(s)) seen.add(s);
        }
        for (Node c : n.getChildNodes()) readNames(c, seen, limit);
    }

    private static String targetName(Expression t) {
        if (t instanceof NameExpr) return ((NameExpr) t).getNameAsString();
        if (t instanceof FieldAccessExpr) return t.toString();
        if (t instanceof ArrayAccessExpr) return targetName(((ArrayAccessExpr) t).getName());
        return null;
    }

    private static List<String> assigned(Statement s) {
        List<String> out = new ArrayList<>();
        if (!(s instanceof ExpressionStmt)) return out;
        Expression e = ((ExpressionStmt) s).getExpression();
        if (e instanceof VariableDeclarationExpr) {
            for (VariableDeclarator v : ((VariableDeclarationExpr) e).getVariables()) out.add(v.getNameAsString());
        } else if (e instanceof AssignExpr) {
            String n = targetName(((AssignExpr) e).getTarget());
            if (n != null) out.add(n);
        } else if (e instanceof UnaryExpr) {
            UnaryExpr u = (UnaryExpr) e;
            UnaryExpr.Operator op = u.getOperator();
            if (op == UnaryExpr.Operator.POSTFIX_INCREMENT || op == UnaryExpr.Operator.POSTFIX_DECREMENT
                    || op == UnaryExpr.Operator.PREFIX_INCREMENT || op == UnaryExpr.Operator.PREFIX_DECREMENT) {
                String n = targetName(u.getExpression());
                if (n != null) out.add(n);
            }
        }
        return out;
    }

    // ------------------------------------------------------------------ blocks

    private List<Pred> block(List<Statement> stmts, List<Pred> preds) {
        List<Statement> group = new ArrayList<>();
        List<Flow.CallInfo> groupCalls = new ArrayList<>();
        for (Statement s : expand(stmts)) {
            if (isSimple(s)) {
                List<Flow.CallInfo> calls = callsOf(s);
                if (interesting(calls).isEmpty()) {
                    group.add(s);
                    groupCalls.addAll(calls);
                    if (group.size() >= MAX_GROUP) {
                        preds = flush(group, groupCalls, preds);
                        group = new ArrayList<>();
                        groupCalls = new ArrayList<>();
                    }
                    continue;
                }
                preds = flush(group, groupCalls, preds);
                group = new ArrayList<>();
                groupCalls = new ArrayList<>();
                preds = callStmt(s, calls, preds);
                continue;
            }
            preds = flush(group, groupCalls, preds);
            group = new ArrayList<>();
            groupCalls = new ArrayList<>();
            preds = stmt(s, preds);
        }
        return flush(group, groupCalls, preds);
    }

    private List<Pred> flush(List<Statement> group, List<Flow.CallInfo> calls, List<Pred> preds) {
        if (group.isEmpty()) return preds;
        Statement first = group.get(0);
        Statement last = group.get(group.size() - 1);
        String label = text(first);
        if (group.size() > 1) label = shorten(label, 70) + "  (+" + (group.size() - 1) + ")";
        Flow.Node n = add("step", label, begin(first), end(last));
        n.own.add(range(begin(first), end(last)));
        for (Statement s : group) {
            for (String a : assigned(s)) if (!n.assigns.contains(a) && n.assigns.size() < 8) n.assigns.add(a);
        }
        n.calls = nonBuiltin(calls, 8);
        link(preds, n.idx);
        return one(n.idx, "next", "");
    }

    private List<Pred> callStmt(Statement s, List<Flow.CallInfo> calls, List<Pred> preds) {
        Flow.Node n = add("call", text(s), begin(s), end(s));
        n.own.add(range(begin(s), end(s)));
        List<Flow.CallInfo> inter = interesting(calls);
        List<Flow.CallInfo> cs = new ArrayList<>(inter);
        int extra = 0;
        for (Flow.CallInfo c : calls) {
            if (!inter.contains(c) && !"builtin".equals(c.kind) && extra < 4) {
                cs.add(c);
                extra++;
            }
        }
        n.calls = cs;
        n.assigns = assigned(s);
        link(preds, n.idx);
        return one(n.idx, "next", "");
    }

    // ------------------------------------------------------------------ statements

    private List<Pred> stmt(Statement s, List<Pred> preds) {
        if (s instanceof ReturnStmt) return sReturn((ReturnStmt) s, preds);
        if (s instanceof ThrowStmt) return sThrow((ThrowStmt) s, preds);
        if (s instanceof IfStmt) return sIf((IfStmt) s, preds, false);
        if (s instanceof ForStmt) return sFor((ForStmt) s, preds);
        if (s instanceof ForEachStmt) return sForEach((ForEachStmt) s, preds);
        if (s instanceof WhileStmt) return sWhile((WhileStmt) s, preds);
        if (s instanceof DoStmt) return sDo((DoStmt) s, preds);
        if (s instanceof BreakStmt) return sBreak((BreakStmt) s, preds);
        if (s instanceof ContinueStmt) return sContinue((ContinueStmt) s, preds);
        if (s instanceof TryStmt) return sTry((TryStmt) s, preds);
        if (s instanceof SynchronizedStmt) return sSync((SynchronizedStmt) s, preds);
        if (s instanceof SwitchStmt) return sSwitch((SwitchStmt) s, preds);
        if (s instanceof LabeledStmt) return sLabeled((LabeledStmt) s, preds);
        if (s instanceof LocalClassDeclarationStmt || s instanceof LocalRecordDeclarationStmt) {
            String name = s instanceof LocalClassDeclarationStmt
                    ? ((LocalClassDeclarationStmt) s).getClassDeclaration().getNameAsString()
                    : ((LocalRecordDeclarationStmt) s).getRecordDeclaration().getNameAsString();
            Flow.Node n = add("step", "class " + name, begin(s), end(s));
            n.own.add(range(begin(s), begin(s)));
            link(preds, n.idx);
            return one(n.idx, "next", "");
        }
        // unknown / opaque statement: a single step
        String t = text(s);
        int nl = t.indexOf('\n');
        Flow.Node n = add("step", nl > 0 ? t.substring(0, nl) : t, begin(s), end(s));
        n.own.add(range(begin(s), end(s)));
        link(preds, n.idx);
        return one(n.idx, "next", "");
    }

    private List<Pred> sReturn(ReturnStmt s, List<Pred> preds) {
        Flow.Node n = add("return", text(s), begin(s), end(s));
        n.own.add(range(begin(s), end(s)));
        if (s.getExpression().isPresent()) {
            n.calls = nonBuiltin(callsOf(s.getExpression().get()), 99);
            n.watch = readNames(s.getExpression().get(), 4);
        }
        link(preds, n.idx);
        returns.add(n.idx);
        return new ArrayList<>();
    }

    private List<Pred> sThrow(ThrowStmt s, List<Pred> preds) {
        Flow.Node n = add("raise", text(s), begin(s), end(s));
        n.own.add(range(begin(s), end(s)));
        n.calls = interesting(callsOf(s.getExpression()));
        link(preds, n.idx);
        if (!handlers.isEmpty() && !handlers.peek().isEmpty()) {
            for (int h : handlers.peek()) edges.add(new Flow.Edge(n.idx, h, "exception", ""));
        }
        return new ArrayList<>();
    }

    private List<Pred> sIf(IfStmt s, List<Pred> preds, boolean isElse) {
        Flow.Node n = add("if", (isElse ? "else if (" : "if (") + text(s.getCondition()) + ")", begin(s), begin(s));
        n.own.add(header(s, s.getThenStmt()));
        n.calls = nonBuiltin(callsOf(s.getCondition()), 99);
        n.watch = readNames(s.getCondition(), 6);
        link(preds, n.idx);
        List<Pred> out = new ArrayList<>(block(stmtsOf(s.getThenStmt()), one(n.idx, "true", "sim")));
        if (s.getElseStmt().isPresent()) {
            Statement el = s.getElseStmt().get();
            if (el instanceof IfStmt) out.addAll(sIf((IfStmt) el, one(n.idx, "false", "não"), true));
            else out.addAll(block(stmtsOf(el), one(n.idx, "false", "não")));
        } else {
            out.add(new Pred(n.idx, "false", "não"));
        }
        return out;
    }

    private String takeLabel() {
        String l = pendingLabel;
        pendingLabel = null;
        return l;
    }

    private List<Pred> loop(Node s, String label, Statement body, List<Pred> preds, List<String> watch,
                            List<String> assigns, boolean infinite, boolean whileLike, List<Flow.CallInfo> calls,
                            int[] extraOwn) {
        String lbl = takeLabel();
        Flow.Node n = add("loop", label, begin(s), begin(s));
        n.own.add(header(s, body));
        if (extraOwn != null) n.own.add(extraOwn);
        n.watch = watch;
        n.assigns = assigns;
        n.calls = nonBuiltin(calls, 99);
        link(preds, n.idx);
        Breakable ctx = new Breakable(true, n.idx, lbl);
        breakables.push(ctx);
        List<Pred> bodyOut = block(stmtsOf(body), one(n.idx, "true", whileLike ? "sim" : "cada"));
        breakables.pop();
        for (Pred p : bodyOut) edges.add(new Flow.Edge(p.src, n.idx, "loop", ""));
        List<Pred> exits = new ArrayList<>();
        if (!infinite) exits.add(new Pred(n.idx, "exit", "fim"));
        exits.addAll(ctx.breaks);
        return exits;
    }

    private List<Pred> sFor(ForStmt s, List<Pred> preds) {
        StringBuilder init = new StringBuilder();
        for (Expression e : s.getInitialization()) {
            if (init.length() > 0) init.append(", ");
            init.append(text(e));
        }
        StringBuilder upd = new StringBuilder();
        for (Expression e : s.getUpdate()) {
            if (upd.length() > 0) upd.append(", ");
            upd.append(text(e));
        }
        String cmp = s.getCompare().map(this::text).orElse("");
        String label = "for (" + init + "; " + cmp + "; " + upd + ")";
        List<String> assigns = new ArrayList<>();
        for (Expression e : s.getInitialization()) {
            if (e instanceof VariableDeclarationExpr) {
                for (VariableDeclarator v : ((VariableDeclarationExpr) e).getVariables()) assigns.add(v.getNameAsString());
            } else if (e instanceof AssignExpr) {
                String t = targetName(((AssignExpr) e).getTarget());
                if (t != null) assigns.add(t);
            }
        }
        boolean infinite = s.getCompare().isEmpty()
                || (s.getCompare().get() instanceof BooleanLiteralExpr && ((BooleanLiteralExpr) s.getCompare().get()).getValue());
        List<Node> hdr = new ArrayList<>(s.getInitialization());
        s.getCompare().ifPresent(hdr::add);
        hdr.addAll(s.getUpdate());
        return loop(s, label, s.getBody(), preds, readNames(s.getCompare().orElse(null), 6), assigns, infinite,
                false, callsOf(hdr), null);
    }

    private List<Pred> sForEach(ForEachStmt s, List<Pred> preds) {
        String var = text(s.getVariable());
        String label = "for (" + var + " : " + text(s.getIterable()) + ")";
        List<String> assigns = new ArrayList<>();
        for (VariableDeclarator v : s.getVariable().getVariables()) assigns.add(v.getNameAsString());
        return loop(s, label, s.getBody(), preds, new ArrayList<>(), assigns, false, false, callsOf(s.getIterable()), null);
    }

    private List<Pred> sWhile(WhileStmt s, List<Pred> preds) {
        boolean infinite = s.getCondition() instanceof BooleanLiteralExpr && ((BooleanLiteralExpr) s.getCondition()).getValue();
        return loop(s, "while (" + text(s.getCondition()) + ")", s.getBody(), preds, readNames(s.getCondition(), 6),
                new ArrayList<>(), infinite, true, callsOf(s.getCondition()), null);
    }

    private List<Pred> sDo(DoStmt s, List<Pred> preds) {
        boolean infinite = s.getCondition() instanceof BooleanLiteralExpr && ((BooleanLiteralExpr) s.getCondition()).getValue();
        int condLine = begin(s.getCondition());
        int[] extra = condLine > 0 ? range(condLine, end(s)) : null;
        return loop(s, "do … while (" + text(s.getCondition()) + ")", s.getBody(), preds, readNames(s.getCondition(), 6),
                new ArrayList<>(), infinite, true, callsOf(s.getCondition()), extra);
    }

    private Breakable findBreakable(String label, boolean loopOnly) {
        for (Breakable b : breakables) { // innermost first
            if (label != null) {
                if (label.equals(b.label)) return b;
                continue;
            }
            if (b.head < 0) continue; // labeled plain block: only a labeled break targets it
            if (loopOnly && !b.loop) continue;
            return b;
        }
        return null;
    }

    private List<Pred> sBreak(BreakStmt s, List<Pred> preds) {
        Flow.Node n = add("break", text(s).replaceAll(";\\s*$", ""), begin(s), begin(s));
        n.own.add(range(begin(s), begin(s)));
        link(preds, n.idx);
        Breakable b = findBreakable(s.getLabel().map(x -> x.getIdentifier()).orElse(null), false);
        if (b != null) b.breaks.add(new Pred(n.idx, "break", ""));
        return new ArrayList<>();
    }

    private List<Pred> sContinue(ContinueStmt s, List<Pred> preds) {
        Flow.Node n = add("continue", text(s).replaceAll(";\\s*$", ""), begin(s), begin(s));
        n.own.add(range(begin(s), begin(s)));
        link(preds, n.idx);
        Breakable b = findBreakable(s.getLabel().map(x -> x.getIdentifier()).orElse(null), true);
        if (b != null && b.head >= 0) edges.add(new Flow.Edge(n.idx, b.head, "loop", ""));
        return new ArrayList<>();
    }

    private List<Pred> sLabeled(LabeledStmt s, List<Pred> preds) {
        Statement inner = s.getStatement();
        String label = s.getLabel().getIdentifier();
        if (inner instanceof ForStmt || inner instanceof ForEachStmt || inner instanceof WhileStmt
                || inner instanceof DoStmt || inner instanceof SwitchStmt) {
            pendingLabel = label;
            return stmt(inner, preds);
        }
        Breakable b = new Breakable(false, -1, label);
        breakables.push(b);
        List<Pred> out = new ArrayList<>(block(stmtsOf(inner), preds));
        breakables.pop();
        out.addAll(b.breaks);
        return out;
    }

    private List<Pred> sSync(SynchronizedStmt s, List<Pred> preds) {
        Flow.Node n = add("with", "synchronized (" + text(s.getExpression()) + ")", begin(s), begin(s));
        n.own.add(header(s, s.getBody()));
        n.calls = nonBuiltin(callsOf(s.getExpression()), 99);
        link(preds, n.idx);
        return block(s.getBody().getStatements(), one(n.idx, "next", ""));
    }

    private List<Pred> sTry(TryStmt s, List<Pred> preds) {
        NodeList<Expression> res = s.getResources();
        StringBuilder rs = new StringBuilder();
        List<String> resNames = new ArrayList<>();
        for (Expression r : res) {
            if (rs.length() > 0) rs.append("; ");
            rs.append(text(r));
            if (r instanceof VariableDeclarationExpr) {
                for (VariableDeclarator v : ((VariableDeclarationExpr) r).getVariables()) resNames.add(v.getNameAsString());
            }
        }
        boolean noHandlers = s.getCatchClauses().isEmpty() && s.getFinallyBlock().isEmpty();
        if (!res.isEmpty() && noHandlers) {
            Flow.Node n = add("with", "try (" + rs + ")", begin(s), begin(s));
            n.own.add(header(s, s.getTryBlock()));
            n.assigns = resNames;
            n.calls = nonBuiltin(callsOf(res), 99);
            link(preds, n.idx);
            return block(s.getTryBlock().getStatements(), one(n.idx, "next", ""));
        }
        Flow.Node t = add("try", res.isEmpty() ? "try" : "try (" + rs + ")", begin(s), begin(s));
        if (res.isEmpty()) t.own.add(range(begin(s), begin(s)));
        else {
            t.own.add(header(s, s.getTryBlock()));
            t.assigns = resNames;
            t.calls = nonBuiltin(callsOf(res), 99);
        }
        link(preds, t.idx);
        List<Integer> handlerNodes = new ArrayList<>();
        trys.push(t.idx);
        for (CatchClause c : s.getCatchClauses()) {
            Flow.Node h = add("except", "catch (" + text(c.getParameter()) + ")", begin(c), begin(c));
            h.own.add(header(c, c.getBody()));
            h.assigns = new ArrayList<>(List.of(c.getParameter().getNameAsString()));
            h.tryParent = t.idx;
            handlerNodes.add(h.idx);
            edges.add(new Flow.Edge(t.idx, h.idx, "exception", "erro"));
        }
        handlers.push(handlerNodes);
        List<Pred> bodyOut = block(s.getTryBlock().getStatements(), one(t.idx, "next", ""));
        handlers.pop();
        trys.pop();
        List<Pred> out = new ArrayList<>(bodyOut);
        Iterator<Integer> hi = handlerNodes.iterator();
        for (CatchClause c : s.getCatchClauses()) {
            int h = hi.next();
            out.addAll(block(c.getBody().getStatements(), one(h, "next", "")));
        }
        if (s.getFinallyBlock().isPresent()) {
            BlockStmt fb = s.getFinallyBlock().get();
            int fl = firstLine(fb);
            Flow.Node f = add("finally", "finally", fl > 0 ? fl : begin(fb), fl > 0 ? fl : begin(fb));
            link(out, f.idx);
            out = block(fb.getStatements(), one(f.idx, "next", ""));
        }
        return out;
    }

    private List<Pred> sSwitch(SwitchStmt s, List<Pred> preds) {
        String lbl = takeLabel();
        NodeList<SwitchEntry> entries = s.getEntries();
        int start = begin(s);
        int firstEntry = entries.isEmpty() ? start + 1 : begin(entries.get(0));
        Flow.Node n = add("match", "switch (" + text(s.getSelector()) + ")", start, start);
        n.own.add(range(start, firstEntry - 1));
        n.watch = readNames(s.getSelector(), 6);
        n.calls = nonBuiltin(callsOf(s.getSelector()), 99);
        link(preds, n.idx);
        Breakable sw = new Breakable(false, n.idx, lbl);
        breakables.push(sw);
        List<Pred> out = new ArrayList<>();
        List<Pred> fallthrough = new ArrayList<>();
        boolean hasDefault = false;
        int prev = n.idx;
        for (SwitchEntry entry : entries) {
            boolean isDefault = entry.getLabels().isEmpty() || entry.isDefault();
            StringBuilder pat = new StringBuilder();
            for (Expression l : entry.getLabels()) {
                if (pat.length() > 0) pat.append(", ");
                pat.append(text(l));
            }
            if (entry.isDefault() && !entry.getLabels().isEmpty()) pat.append(", default");
            entry.getGuard().ifPresent(g -> pat.append(" when ").append(text(g)));
            String patS = isDefault && entry.getLabels().isEmpty() ? "default" : pat.toString();
            if (isDefault) hasDefault = true;
            String label = patS.equals("default") ? "default" : "case " + patS;
            List<Statement> body = entry.getStatements();
            int eb = begin(entry);
            int fb = -1;
            for (Statement x : body) {
                fb = firstLine(x) > 0 ? firstLine(x) : begin(x);
                if (fb > 0) break;
            }
            Flow.Node c = add("case", label, eb, eb);
            c.own.add(range(eb, fb > 0 ? fb - 1 : eb));
            edges.add(new Flow.Edge(prev, c.idx, prev == n.idx ? "case" : "false", prev == n.idx ? shorten(patS, 40) : "não"));
            boolean arrow = entry.getType() != SwitchEntry.Type.STATEMENT_GROUP;
            List<Pred> bodyPreds = one(c.idx, "true", "sim");
            if (!arrow) bodyPreds.addAll(fallthrough);
            List<Pred> bodyOut = block(body, bodyPreds);
            if (arrow) {
                out.addAll(bodyOut);
                out.addAll(fallthrough);
                fallthrough = new ArrayList<>();
            } else {
                fallthrough = new ArrayList<>(bodyOut);
            }
            prev = c.idx;
        }
        out.addAll(fallthrough);
        breakables.pop();
        out.addAll(sw.breaks);
        if (!hasDefault) out.add(new Pred(prev, "false", "nenhum"));
        return out;
    }

    // ------------------------------------------------------------------ util

    static String sha1(String s) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-1");
            byte[] d = md.digest(s.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder();
            for (byte b : d) sb.append(String.format("%02x", b));
            return sb.toString();
        } catch (Exception e) {
            return Integer.toHexString(s.hashCode()) + "000000000000";
        }
    }
}
