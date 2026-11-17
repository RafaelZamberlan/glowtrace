package io.easyapi.agent.instrument;

import io.easyapi.agent.runtime.Rec;
import net.bytebuddy.asm.Advice;
import net.bytebuddy.implementation.bytecode.assign.Assigner;

/** Inlined into every project method: records args on enter, return value / exception on exit. */
public final class MethodAdvice {
    private MethodAdvice() {}

    @Advice.OnMethodEnter(suppress = Throwable.class)
    public static Object enter(@Advice.Origin("#t|#m|#d") String key,
                               @Advice.AllArguments(typing = Assigner.Typing.DYNAMIC) Object[] args) {
        if (!Rec.active()) return null; // args array is only built inside this branch
        return Rec.enter(key, args);
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class, suppress = Throwable.class)
    public static void exit(@Advice.Enter Object frame,
                            @Advice.Return(typing = Assigner.Typing.DYNAMIC) Object ret,
                            @Advice.Thrown Throwable thrown) {
        if (frame != null) Rec.exit(frame, ret, thrown);
    }
}
