package io.easyapi.agent.analysis;

import com.github.javaparser.JavaParser;
import com.github.javaparser.ParseResult;
import com.github.javaparser.ParserConfiguration;
import com.github.javaparser.Range;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.ImportDeclaration;
import com.github.javaparser.ast.Modifier;
import com.github.javaparser.ast.body.BodyDeclaration;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.EnumDeclaration;
import com.github.javaparser.ast.body.FieldDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.Parameter;
import com.github.javaparser.ast.body.RecordDeclaration;
import com.github.javaparser.ast.body.TypeDeclaration;
import com.github.javaparser.ast.body.VariableDeclarator;
import com.github.javaparser.ast.expr.AssignExpr;
import com.github.javaparser.ast.expr.Expression;
import com.github.javaparser.ast.expr.FieldAccessExpr;
import com.github.javaparser.ast.expr.LiteralExpr;
import com.github.javaparser.ast.expr.NameExpr;
import com.github.javaparser.ast.expr.ThisExpr;
import com.github.javaparser.ast.stmt.BlockStmt;
import com.github.javaparser.ast.stmt.ExpressionStmt;
import com.github.javaparser.ast.stmt.ReturnStmt;
import com.github.javaparser.ast.stmt.Statement;
import com.github.javaparser.ast.type.ClassOrInterfaceType;
import com.github.javaparser.ast.type.Type;
import io.easyapi.agent.Log;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.FileVisitResult;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.TreeMap;
import java.util.concurrent.ConcurrentHashMap;

/** Parsed project sources: files, types, methods, fn_ids and a small type resolver. */
public final class ProjectIndex {

    // ------------------------------------------------------------------ model

    public static final class SourceFile {
        public final Path path;
        public final String rel;
        public final String[] lines;
        public final CompilationUnit cu;
        public final String pkg;
        final Map<String, String> singleImports = new HashMap<>(); // simple -> fqn
        final List<String> wildcardImports = new ArrayList<>(); // package (or class) names
        final Map<String, String> staticImports = new HashMap<>(); // member -> class fqn
        final List<String> staticWildcards = new ArrayList<>(); // class fqn
        final List<TypeInfo> topTypes = new ArrayList<>();

        SourceFile(Path path, String rel, String text, CompilationUnit cu) {
            this.path = path;
            this.rel = rel;
            this.lines = text.split("\r\n|\r|\n", -1);
            this.cu = cu;
            this.pkg = cu.getPackageDeclaration().map(p -> p.getNameAsString()).orElse("");
            for (ImportDeclaration imp : cu.getImports()) {
                String n = imp.getNameAsString();
                if (imp.isStatic()) {
                    if (imp.isAsterisk()) staticWildcards.add(n);
                    else {
                        int dot = n.lastIndexOf('.');
                        if (dot > 0) staticImports.put(n.substring(dot + 1), n.substring(0, dot));
                    }
                } else if (imp.isAsterisk()) {
                    wildcardImports.add(n);
                } else {
                    int dot = n.lastIndexOf('.');
                    singleImports.put(dot >= 0 ? n.substring(dot + 1) : n, n);
                }
            }
        }

        /** Original source text of a node (not pretty-printed). */
        public String text(com.github.javaparser.ast.Node n) {
            Optional<Range> r = n.getRange();
            if (r.isEmpty()) return n.toString();
            String s = slice(r.get());
            return s.isEmpty() ? n.toString() : s;
        }

        public String slice(Range r) {
            int bl = r.begin.line, bc = r.begin.column, el = r.end.line, ec = r.end.column;
            if (bl < 1 || el > lines.length || el < bl) return "";
            if (bl == el) return sub(lines[bl - 1], bc - 1, ec);
            StringBuilder sb = new StringBuilder(sub(lines[bl - 1], bc - 1, lines[bl - 1].length()));
            for (int i = bl; i < el - 1; i++) sb.append('\n').append(lines[i]);
            sb.append('\n').append(sub(lines[el - 1], 0, ec));
            return sb.toString();
        }

        public String lineRange(int from, int to) {
            StringBuilder sb = new StringBuilder();
            for (int i = Math.max(1, from); i <= Math.min(to, lines.length); i++) {
                if (sb.length() > 0 || i > Math.max(1, from)) sb.append('\n');
                sb.append(lines[i - 1]);
            }
            return sb.toString();
        }

        private static String sub(String s, int a, int b) {
            a = Math.max(0, Math.min(a, s.length()));
            b = Math.max(a, Math.min(b, s.length()));
            return s.substring(a, b);
        }
    }

    public static final class FieldInfo {
        public final String name;
        public final Type type;
        public final Expression init;
        public final boolean isStatic;
        public final TypeInfo owner;

        FieldInfo(String name, Type type, Expression init, boolean isStatic, TypeInfo owner) {
            this.name = name;
            this.type = type;
            this.init = init;
            this.isStatic = isStatic;
            this.owner = owner;
        }
    }

    public static final class TypeInfo {
        public final String simpleName;
        public final String qualName; // Outer.Inner
        public final String binaryName; // pkg.Outer$Inner
        public final String fqn; // pkg.Outer.Inner
        public final SourceFile file;
        public final TypeDeclaration<?> decl;
        public final TypeInfo outer;
        public boolean isInterface;
        public boolean isAbstract;
        final List<ClassOrInterfaceType> superTypeNodes = new ArrayList<>();
        public final List<TypeInfo> supers = new ArrayList<>(); // project supertypes (superclass first)
        public final List<String> externalSupers = new ArrayList<>(); // fqn of non-project supertypes
        final Map<String, TypeInfo> nested = new LinkedHashMap<>();
        final Map<String, FieldInfo> fields = new LinkedHashMap<>();
        public final List<MethodDef> methods = new ArrayList<>();

        TypeInfo(String simpleName, String qualName, String binaryName, String fqn, SourceFile file,
                 TypeDeclaration<?> decl, TypeInfo outer) {
            this.simpleName = simpleName;
            this.qualName = qualName;
            this.binaryName = binaryName;
            this.fqn = fqn;
            this.file = file;
            this.decl = decl;
            this.outer = outer;
        }

        @Override
        public String toString() {
            return fqn;
        }
    }

    public static final class MethodDef {
        public final TypeInfo owner;
        public final MethodDeclaration decl;
        public final String name;
        public final int paramCount;
        public final boolean hasBody;
        public final boolean trivial;
        public String fnId;
        public String qualname;

        MethodDef(TypeInfo owner, MethodDeclaration decl) {
            this.owner = owner;
            this.decl = decl;
            this.name = decl.getNameAsString();
            this.paramCount = decl.getParameters().size();
            this.hasBody = decl.getBody().isPresent();
            this.trivial = isTrivial(decl);
        }

        boolean varargs() {
            return paramCount > 0 && decl.getParameter(paramCount - 1).isVarArgs();
        }
    }

    /** Either a project type or the FQN of an external (library/JDK) type. */
    public static final class TypeRef {
        public final TypeInfo type;
        public final String external;

        TypeRef(TypeInfo type, String external) {
            this.type = type;
            this.external = external;
        }
    }

    // ------------------------------------------------------------------ state

    public final List<SourceFile> files = new ArrayList<>();
    public final List<TypeInfo> types = new ArrayList<>();
    final Map<String, TypeInfo> byFqn = new HashMap<>();
    final Map<String, List<TypeInfo>> bySimple = new HashMap<>();
    final Set<String> projectPackages = new HashSet<>();
    public final Map<String, MethodDef> byFnId = new LinkedHashMap<>();
    /** "binaryName#method#paramCount" -> fn_id (non-trivial methods only). */
    final Map<String, String> runtimeKeys = new HashMap<>();
    final Map<String, String> runtimeKeysByName = new HashMap<>(); // "binary#method" -> fn_id when unique
    private Map<TypeInfo, List<TypeInfo>> subtypes;
    private final Map<String, Boolean> bootstrapCache = new ConcurrentHashMap<>();
    public int parseErrors;
    public final Path root;

    private ProjectIndex(Path root) {
        this.root = root;
    }

    // ------------------------------------------------------------------ build

    public static ProjectIndex build(List<Path> sourceRoots, Path root, boolean generated) {
        ProjectIndex idx = new ProjectIndex(root);
        LinkedHashSet<Path> javaFiles = new LinkedHashSet<>();
        List<Path> dirs = new ArrayList<>(sourceRoots);
        if (generated && root != null) {
            for (String g : new String[] {"target/generated-sources", "build/generated/sources", "build/generated"}) {
                Path p = root.resolve(g);
                if (Files.isDirectory(p) && !dirs.contains(p)) dirs.add(p);
            }
        }
        for (Path d : dirs) collectJava(d, javaFiles);
        ParserConfiguration cfg = new ParserConfiguration();
        cfg.setLanguageLevel(ParserConfiguration.LanguageLevel.JAVA_21);
        cfg.setAttributeComments(true);
        JavaParser parser = new JavaParser(cfg);
        TreeMap<String, Path> sorted = new TreeMap<>();
        for (Path f : javaFiles) sorted.put(relPath(root, f), f);
        for (Map.Entry<String, Path> e : sorted.entrySet()) {
            try {
                String text = read(e.getValue());
                ParseResult<CompilationUnit> res = parser.parse(text);
                if (!res.isSuccessful()) {
                    idx.parseErrors++;
                    Log.debug("parse problems in " + e.getKey() + ": " + res.getProblems());
                }
                if (res.getResult().isEmpty()) continue;
                SourceFile sf = new SourceFile(e.getValue(), e.getKey(), text, res.getResult().get());
                idx.files.add(sf);
                if (!sf.pkg.isEmpty()) idx.projectPackages.add(sf.pkg);
                for (TypeDeclaration<?> td : sf.cu.getTypes()) idx.addType(sf, td, null);
            } catch (Throwable t) {
                idx.parseErrors++;
                Log.debug("cannot parse " + e.getKey() + ": " + t);
            }
        }
        idx.linkSupertypes();
        idx.assignFnIds();
        return idx;
    }

    private static void collectJava(Path dir, Set<Path> out) {
        if (!Files.isDirectory(dir)) return;
        try {
            Files.walkFileTree(dir, new SimpleFileVisitor<>() {
                @Override
                public FileVisitResult preVisitDirectory(Path d, BasicFileAttributes attrs) {
                    String n = d.getFileName() == null ? "" : d.getFileName().toString();
                    String s = d.toString().replace('\\', '/');
                    if (n.startsWith(".") && !d.equals(dir)) return FileVisitResult.SKIP_SUBTREE;
                    if (n.equals("node_modules") || s.endsWith("/src/test") || s.contains("/src/test/")
                            || s.endsWith("/generated-test-sources")) {
                        return FileVisitResult.SKIP_SUBTREE;
                    }
                    return FileVisitResult.CONTINUE;
                }

                @Override
                public FileVisitResult visitFile(Path f, BasicFileAttributes attrs) {
                    String n = f.getFileName().toString();
                    if (n.endsWith(".java") && !n.equals("module-info.java") && !n.equals("package-info.java")) {
                        out.add(f.toAbsolutePath().normalize());
                    }
                    return FileVisitResult.CONTINUE;
                }
            });
        } catch (IOException e) {
            Log.warn("cannot walk " + dir + ": " + e);
        }
    }

    static String relPath(Path root, Path f) {
        try {
            if (root != null && f.startsWith(root)) return root.relativize(f).toString().replace('\\', '/');
        } catch (Exception ignored) {
            // fall through
        }
        return f.toString().replace('\\', '/');
    }

    private static String read(Path p) throws IOException {
        byte[] bytes = Files.readAllBytes(p);
        String s;
        try {
            s = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
        } catch (CharacterCodingException e) {
            s = new String(bytes, StandardCharsets.ISO_8859_1);
        }
        if (!s.isEmpty() && s.charAt(0) == '﻿') s = s.substring(1);
        return s;
    }

    private void addType(SourceFile sf, TypeDeclaration<?> td, TypeInfo outer) {
        String name = td.getNameAsString();
        String qual = outer == null ? name : outer.qualName + "." + name;
        String bin = outer == null ? (sf.pkg.isEmpty() ? name : sf.pkg + "." + name) : outer.binaryName + "$" + name;
        String fqn = outer == null ? (sf.pkg.isEmpty() ? name : sf.pkg + "." + name) : outer.fqn + "." + name;
        TypeInfo t = new TypeInfo(name, qual, bin, fqn, sf, td, outer);
        if (td instanceof ClassOrInterfaceDeclaration) {
            ClassOrInterfaceDeclaration c = (ClassOrInterfaceDeclaration) td;
            t.isInterface = c.isInterface();
            t.isAbstract = c.isAbstract() || c.isInterface();
            t.superTypeNodes.addAll(c.getExtendedTypes());
            t.superTypeNodes.addAll(c.getImplementedTypes());
        } else if (td instanceof EnumDeclaration) {
            t.superTypeNodes.addAll(((EnumDeclaration) td).getImplementedTypes());
        } else if (td instanceof RecordDeclaration) {
            RecordDeclaration r = (RecordDeclaration) td;
            t.superTypeNodes.addAll(r.getImplementedTypes());
            for (Parameter p : r.getParameters()) {
                t.fields.put(p.getNameAsString(), new FieldInfo(p.getNameAsString(), p.getType(), null, false, t));
            }
        } else {
            // annotation declarations: nothing to execute
            t.isInterface = true;
            t.isAbstract = true;
        }
        types.add(t);
        byFqn.put(fqn, t);
        bySimple.computeIfAbsent(name, k -> new ArrayList<>()).add(t);
        if (outer == null) sf.topTypes.add(t);
        else outer.nested.put(name, t);
        boolean iface = t.isInterface;
        for (BodyDeclaration<?> member : td.getMembers()) {
            if (member instanceof FieldDeclaration) {
                FieldDeclaration fd = (FieldDeclaration) member;
                boolean st = iface || fd.isStatic();
                for (VariableDeclarator v : fd.getVariables()) {
                    t.fields.put(v.getNameAsString(),
                            new FieldInfo(v.getNameAsString(), v.getType(), v.getInitializer().orElse(null), st, t));
                }
            } else if (member instanceof MethodDeclaration) {
                t.methods.add(new MethodDef(t, (MethodDeclaration) member));
            } else if (member instanceof TypeDeclaration) {
                addType(sf, (TypeDeclaration<?>) member, t);
            }
        }
    }

    private void linkSupertypes() {
        for (TypeInfo t : types) {
            for (ClassOrInterfaceType st : t.superTypeNodes) {
                TypeRef r = resolve(st.getNameWithScope(), t.outer, t.file);
                if (r == null) continue;
                if (r.type != null && r.type != t) t.supers.add(r.type);
                else if (r.external != null) t.externalSupers.add(r.external);
            }
        }
    }

    private void assignFnIds() {
        for (TypeInfo t : types) {
            Map<String, Integer> counts = new HashMap<>();
            for (MethodDef m : t.methods) counts.merge(m.name, 1, Integer::sum);
            for (MethodDef m : t.methods) {
                String q = t.qualName + "." + m.name;
                String id = t.file.rel + "::" + q;
                if (counts.get(m.name) > 1) id = id + "#" + m.paramCount;
                String base = id;
                int k = 2;
                while (byFnId.containsKey(id)) id = base + "_" + k++;
                m.fnId = id;
                m.qualname = q;
                byFnId.put(id, m);
                if (!m.trivial && m.hasBody) {
                    runtimeKeys.putIfAbsent(t.binaryName + "#" + m.name + "#" + m.paramCount, id);
                    String nk = t.binaryName + "#" + m.name;
                    if (runtimeKeysByName.containsKey(nk)) runtimeKeysByName.put(nk, null);
                    else runtimeKeysByName.put(nk, id);
                }
            }
        }
    }

    /** getters/setters/fluent setters/equals/hashCode/toString: not shown as frames (like attribute access in Python). */
    static boolean isTrivial(MethodDeclaration m) {
        String n = m.getNameAsString();
        int pc = m.getParameters().size();
        if ((n.equals("toString") || n.equals("hashCode")) && pc == 0) return true;
        if (n.equals("equals") && pc == 1) return true;
        if (m.getBody().isEmpty() || pc > 1) return false;
        BlockStmt body = m.getBody().get();
        List<Statement> stmts = body.getStatements();
        if (stmts.isEmpty() || stmts.size() > 2) return false;
        for (Statement s : stmts) {
            if (s instanceof ReturnStmt) {
                Optional<Expression> e = ((ReturnStmt) s).getExpression();
                if (e.isPresent() && !simpleValue(e.get())) return false;
            } else if (s instanceof ExpressionStmt && ((ExpressionStmt) s).getExpression() instanceof AssignExpr) {
                AssignExpr a = (AssignExpr) ((ExpressionStmt) s).getExpression();
                if (a.getOperator() != AssignExpr.Operator.ASSIGN) return false;
                if (!(a.getTarget() instanceof NameExpr || isThisField(a.getTarget()))) return false;
                if (!simpleValue(a.getValue())) return false;
            } else {
                return false;
            }
        }
        return true;
    }

    private static boolean isThisField(Expression e) {
        return e instanceof FieldAccessExpr && ((FieldAccessExpr) e).getScope() instanceof ThisExpr;
    }

    private static boolean simpleValue(Expression e) {
        return e instanceof NameExpr || e instanceof LiteralExpr || e instanceof ThisExpr || isThisField(e);
    }

    // ------------------------------------------------------------------ queries

    public TypeInfo type(String fqn) {
        return byFqn.get(fqn);
    }

    public String runtimeFn(String binaryName, String method, int paramCount) {
        String id = runtimeKeys.get(binaryName + "#" + method + "#" + paramCount);
        return id;
    }

    static TypeRef ref(TypeInfo t) {
        return new TypeRef(t, null);
    }

    static TypeRef ext(String fqn) {
        return new TypeRef(null, fqn);
    }

    /** Resolve a (possibly qualified) type name as seen from {@code ctx}/{@code sf}. */
    public TypeRef resolve(String name, TypeInfo ctx, SourceFile sf) {
        if (name == null) return null;
        int lt = name.indexOf('<');
        if (lt >= 0) name = name.substring(0, lt);
        name = name.trim();
        if (name.isEmpty() || name.equals("var")) return null;
        if (name.indexOf('.') > 0) {
            TypeInfo t = byFqn.get(name);
            if (t != null) return ref(t);
            int dot = name.indexOf('.');
            String first = name.substring(0, dot);
            String rest = name.substring(dot + 1);
            TypeRef base = Character.isUpperCase(first.charAt(0)) ? resolveSimple(first, ctx, sf) : null;
            if (base != null && base.type != null) {
                TypeInfo cur = base.type;
                for (String seg : rest.split("\\.")) {
                    cur = cur == null ? null : nestedLookup(cur, seg, 0);
                }
                if (cur != null) return ref(cur);
                return null;
            }
            if (base != null && base.external != null) return ext(base.external + "." + rest);
            if (Character.isLowerCase(first.charAt(0))) return ext(name);
            return null;
        }
        return resolveSimple(name, ctx, sf);
    }

    private TypeRef resolveSimple(String name, TypeInfo ctx, SourceFile sf) {
        for (TypeInfo t = ctx; t != null; t = t.outer) {
            if (t.simpleName.equals(name)) return ref(t);
            TypeInfo n = nestedLookup(t, name, 0);
            if (n != null) return ref(n);
        }
        if (sf != null) {
            for (TypeInfo t : sf.topTypes) if (t.simpleName.equals(name)) return ref(t);
            String fqn = sf.singleImports.get(name);
            if (fqn != null) {
                TypeInfo t = byFqn.get(fqn);
                return t != null ? ref(t) : ext(fqn);
            }
            TypeInfo same = byFqn.get(sf.pkg.isEmpty() ? name : sf.pkg + "." + name);
            if (same != null) return ref(same);
            for (String pkg : sf.wildcardImports) {
                TypeInfo t = byFqn.get(pkg + "." + name);
                if (t != null) return ref(t);
            }
        }
        if (bootstrapHas("java.lang." + name)) return ext("java.lang." + name);
        if (sf != null) {
            for (String pkg : sf.wildcardImports) {
                if ((pkg.startsWith("java.") || pkg.startsWith("javax.")) && bootstrapHas(pkg + "." + name)) {
                    return ext(pkg + "." + name);
                }
            }
            for (String pkg : sf.wildcardImports) {
                if (!pkg.startsWith("java.") && !projectPackages.contains(pkg)) return ext(pkg + "." + name);
            }
        }
        List<TypeInfo> l = bySimple.get(name);
        if (l != null && l.size() == 1) return ref(l.get(0));
        return null;
    }

    private TypeInfo nestedLookup(TypeInfo t, String name, int depth) {
        if (depth > 8) return null;
        TypeInfo n = t.nested.get(name);
        if (n != null) return n;
        for (TypeInfo s : t.supers) {
            n = nestedLookup(s, name, depth + 1);
            if (n != null) return n;
        }
        return null;
    }

    private boolean bootstrapHas(String fqn) {
        return bootstrapCache.computeIfAbsent(fqn, k -> {
            try {
                Class.forName(k, false, null);
                return true;
            } catch (Throwable e) {
                return false;
            }
        });
    }

    /** t, then its project supertypes (BFS; superclass before interfaces). */
    public List<TypeInfo> hierarchy(TypeInfo t) {
        List<TypeInfo> out = new ArrayList<>();
        Deque<TypeInfo> q = new ArrayDeque<>();
        Set<TypeInfo> seen = new HashSet<>();
        q.add(t);
        while (!q.isEmpty() && out.size() < 64) {
            TypeInfo x = q.poll();
            if (!seen.add(x)) continue;
            out.add(x);
            q.addAll(x.supers);
        }
        return out;
    }

    public List<String> allExternalSupers(TypeInfo t) {
        List<String> out = new ArrayList<>();
        for (TypeInfo x : hierarchy(t)) {
            for (String e : x.externalSupers) if (!out.contains(e)) out.add(e);
        }
        return out;
    }

    public boolean isSpringData(TypeInfo t) {
        if (t == null) return false;
        for (String e : allExternalSupers(t)) {
            if (e.startsWith("org.springframework.data.")) return true;
        }
        return false;
    }

    /** Method lookup by name + arg count in t and its project supertypes. */
    public MethodDef findMethod(TypeInfo t, String name, int argc) {
        MethodDef varargMatch = null;
        for (TypeInfo x : hierarchy(t)) {
            for (MethodDef m : x.methods) {
                if (!m.name.equals(name)) continue;
                if (m.paramCount == argc) return m;
                if (varargMatch == null && m.varargs() && argc >= m.paramCount - 1) varargMatch = m;
            }
        }
        return varargMatch;
    }

    public FieldInfo findField(TypeInfo t, String name) {
        for (TypeInfo x : hierarchy(t)) {
            FieldInfo f = x.fields.get(name);
            if (f != null) return f;
        }
        return null;
    }

    private synchronized Map<TypeInfo, List<TypeInfo>> subtypes() {
        if (subtypes == null) {
            Map<TypeInfo, List<TypeInfo>> m = new HashMap<>();
            for (TypeInfo t : types) {
                for (TypeInfo s : hierarchy(t)) {
                    if (s != t) m.computeIfAbsent(s, k -> new ArrayList<>()).add(t);
                }
            }
            subtypes = m;
        }
        return subtypes;
    }

    /** The single concrete project implementation of an abstract/interface method, or null. */
    public MethodDef uniqueImplementation(MethodDef m, TypeInfo staticType) {
        Set<MethodDef> found = new LinkedHashSet<>();
        TypeInfo base = staticType != null ? staticType : m.owner;
        for (TypeInfo impl : subtypes().getOrDefault(base, Collections.emptyList())) {
            if (impl.isInterface || impl.isAbstract) continue;
            MethodDef d = findMethod(impl, m.name, m.paramCount);
            if (d != null && d.hasBody) found.add(d);
        }
        return found.size() == 1 ? found.iterator().next() : null;
    }

    public static boolean isStatic(MethodDeclaration d) {
        return d.hasModifier(Modifier.Keyword.STATIC);
    }

    public int methodCount() {
        return byFnId.size();
    }
}
