package io.glowtrace.agent.instrument;

import io.glowtrace.agent.runtime.Rec;
import net.bytebuddy.asm.Advice;

/** Inlined into the servlet entry points: opens / closes the per-request recorder (outermost call only). */
public final class ServletAdvice {
    private ServletAdvice() {}

    @Advice.OnMethodEnter(suppress = Throwable.class)
    public static Object enter(@Advice.Argument(0) Object req, @Advice.Argument(1) Object resp) {
        return Rec.beginRequest(req, resp);
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class, suppress = Throwable.class)
    public static void exit(@Advice.Enter Object rec, @Advice.Argument(0) Object req, @Advice.Argument(1) Object resp,
                            @Advice.Thrown Throwable thrown) {
        if (rec != null) Rec.endRequest(rec, req, resp, thrown);
    }
}
