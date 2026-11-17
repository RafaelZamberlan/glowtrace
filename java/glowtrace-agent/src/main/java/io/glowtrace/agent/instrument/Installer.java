package io.glowtrace.agent.instrument;

import io.glowtrace.agent.Config;
import io.glowtrace.agent.Log;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import net.bytebuddy.asm.AsmVisitorWrapper;
import net.bytebuddy.description.method.MethodDescription;
import net.bytebuddy.description.type.TypeDescription;
import net.bytebuddy.dynamic.DynamicType;
import net.bytebuddy.matcher.ElementMatcher;
import net.bytebuddy.utility.JavaModule;

import java.lang.instrument.Instrumentation;
import java.util.concurrent.atomic.AtomicInteger;

import static net.bytebuddy.matcher.ElementMatchers.isAbstract;
import static net.bytebuddy.matcher.ElementMatchers.isAnnotation;
import static net.bytebuddy.matcher.ElementMatchers.isBridge;
import static net.bytebuddy.matcher.ElementMatchers.isMethod;
import static net.bytebuddy.matcher.ElementMatchers.isNative;
import static net.bytebuddy.matcher.ElementMatchers.isSynthetic;
import static net.bytebuddy.matcher.ElementMatchers.nameContains;
import static net.bytebuddy.matcher.ElementMatchers.nameStartsWith;
import static net.bytebuddy.matcher.ElementMatchers.named;
import static net.bytebuddy.matcher.ElementMatchers.none;
import static net.bytebuddy.matcher.ElementMatchers.not;
import static net.bytebuddy.matcher.ElementMatchers.takesArgument;
import static net.bytebuddy.matcher.ElementMatchers.takesArguments;

/** Byte Buddy setup: project classes (method advice + line probes) and servlet entry points. */
public final class Installer {
    private Installer() {}

    public static final AtomicInteger TRANSFORMED = new AtomicInteger();

    public static void install(Config cfg, Instrumentation inst) {
        ElementMatcher.Junction<TypeDescription> app = none();
        for (String p : cfg.packages) app = app.or(nameStartsWith(p + ".")).or(named(p));
        ElementMatcher.Junction<MethodDescription> recorded = isMethod().and(not(isAbstract())).and(not(isNative()))
                .and(not(isSynthetic())).and(not(isBridge()));
        ElementMatcher.Junction<MethodDescription> probed = isMethod().and(not(isAbstract())).and(not(isNative()))
                .and(not(isBridge()));

        AgentBuilder.Listener listener = new AgentBuilder.Listener.Adapter() {
            @Override
            public void onTransformation(TypeDescription typeDescription, ClassLoader classLoader, JavaModule module,
                                         boolean loaded, DynamicType dynamicType) {
                TRANSFORMED.incrementAndGet();
                Log.debug("instrumented " + typeDescription.getName());
            }

            @Override
            public void onError(String typeName, ClassLoader classLoader, JavaModule module, boolean loaded,
                                Throwable throwable) {
                Log.internal("instrumenting " + typeName, throwable);
            }
        };

        new AgentBuilder.Default()
                .disableClassFormatChanges()
                .with(AgentBuilder.TypeStrategy.Default.DECORATE)
                .with(listener)
                .ignore(nameStartsWith("io.glowtrace.agent.")
                        .or(nameStartsWith("net.bytebuddy."))
                        .or(nameContains("$$"))
                        .or(nameContains("$HibernateProxy$"))
                        .or(nameContains("$ByteBuddy$"))
                        .or(isSynthetic()))
                .type(app.and(not(isAnnotation())))
                .transform((builder, type, loader, module, pd) -> builder
                        .visit(Advice.to(MethodAdvice.class).on(recorded))
                        .visit(new AsmVisitorWrapper.ForDeclaredMethods().invokable(probed, new LineProbes())))
                .type(named("jakarta.servlet.http.HttpServlet").or(named("javax.servlet.http.HttpServlet")))
                .transform((builder, type, loader, module, pd) -> builder
                        .visit(Advice.to(ServletAdvice.class).on(named("service").and(takesArguments(2))
                                .and(takesArgument(0, named("jakarta.servlet.ServletRequest")
                                        .or(named("javax.servlet.ServletRequest")))))))
                .type(named("org.apache.catalina.core.ApplicationFilterChain"))
                .transform((builder, type, loader, module, pd) -> builder
                        .visit(Advice.to(ServletAdvice.class).on(named("doFilter").and(takesArguments(2)))))
                .installOn(inst);
    }
}
