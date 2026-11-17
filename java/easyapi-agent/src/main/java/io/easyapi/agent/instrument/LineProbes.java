package io.easyapi.agent.instrument;

import io.easyapi.agent.runtime.MethodTable;
import io.easyapi.agent.runtime.Rec;
import net.bytebuddy.asm.AsmVisitorWrapper;
import net.bytebuddy.description.method.MethodDescription;
import net.bytebuddy.description.type.TypeDescription;
import net.bytebuddy.implementation.Implementation;
import net.bytebuddy.jar.asm.Handle;
import net.bytebuddy.jar.asm.Label;
import net.bytebuddy.jar.asm.MethodVisitor;
import net.bytebuddy.jar.asm.Opcodes;
import net.bytebuddy.pool.TypePool;
import net.bytebuddy.utility.OpenedClassReader;

/**
 * Inserts {@code Rec.line(methodId, line)} at the first instruction of every source line, and
 * {@code Rec.thrown(ex, methodId)} before every {@code athrow}.
 *
 * <p>The probe is emitted lazily at the next real instruction (not inside visitLineNumber) so that it lands
 * after any stack-map frame recorded for the same offset.
 */
public final class LineProbes implements AsmVisitorWrapper.ForDeclaredMethods.MethodVisitorWrapper {
    private static final String REC = Rec.class.getName().replace('.', '/');

    @Override
    public MethodVisitor wrap(TypeDescription instrumentedType, MethodDescription instrumentedMethod,
                              MethodVisitor methodVisitor, Implementation.Context implementationContext,
                              TypePool typePool, int writerFlags, int readerFlags) {
        int mid = MethodTable.register(instrumentedType.getName(), instrumentedMethod.getInternalName(),
                instrumentedMethod.getDescriptor());
        return new Probe(methodVisitor, mid);
    }

    static final class Probe extends MethodVisitor {
        private final int mid;
        private int pending = -1;
        private int lastLine = -1;

        Probe(MethodVisitor mv, int mid) {
            super(OpenedClassReader.ASM_API, mv);
            this.mid = mid;
        }

        private void push(int v) {
            if (v >= -1 && v <= 5) super.visitInsn(Opcodes.ICONST_0 + v);
            else if (v >= Byte.MIN_VALUE && v <= Byte.MAX_VALUE) super.visitIntInsn(Opcodes.BIPUSH, v);
            else if (v >= Short.MIN_VALUE && v <= Short.MAX_VALUE) super.visitIntInsn(Opcodes.SIPUSH, v);
            else super.visitLdcInsn(v);
        }

        private void flush() {
            if (pending < 0) return;
            int line = pending;
            pending = -1;
            push(mid);
            push(line);
            super.visitMethodInsn(Opcodes.INVOKESTATIC, REC, "line", "(II)V", false);
        }

        @Override
        public void visitLineNumber(int line, Label start) {
            super.visitLineNumber(line, start);
            pending = line;
            lastLine = line;
        }

        /**
         * A stack-map frame marks a jump target. Back-jumps of loops (e.g. the hasNext() check of a for-each)
         * land in the middle of a line's range, where no LineNumber entry starts: re-announce the current line
         * there so loop heads are visited once per iteration (like Python's line events on backward jumps).
         */
        @Override
        public void visitFrame(int type, int numLocal, Object[] local, int numStack, Object[] stack) {
            super.visitFrame(type, numLocal, local, numStack, stack);
            if (pending < 0 && lastLine > 0) pending = lastLine;
        }

        @Override
        public void visitInsn(int opcode) {
            flush();
            if (opcode == Opcodes.ATHROW) {
                super.visitInsn(Opcodes.DUP);
                push(mid);
                super.visitMethodInsn(Opcodes.INVOKESTATIC, REC, "thrown", "(Ljava/lang/Throwable;I)V", false);
            }
            super.visitInsn(opcode);
        }

        @Override
        public void visitIntInsn(int opcode, int operand) {
            flush();
            super.visitIntInsn(opcode, operand);
        }

        @Override
        public void visitVarInsn(int opcode, int var) {
            flush();
            super.visitVarInsn(opcode, var);
        }

        @Override
        public void visitTypeInsn(int opcode, String type) {
            if (opcode == Opcodes.NEW) {
                // Stack-map frames copied from the original class describe an object under construction as
                // Uninitialized(<label of the NEW>). A probe emitted before NEW would sit at that label's offset,
                // the label would point at the probe and the JVM rejects the class ("bad offset for
                // Uninitialized"), e.g. `new X(a, cond ? b : c)`. Emit NEW first, then the probe: calling a
                // static method with an uninitialized reference on the stack is legal.
                super.visitTypeInsn(opcode, type);
                flush();
                return;
            }
            flush();
            super.visitTypeInsn(opcode, type);
        }

        @Override
        public void visitFieldInsn(int opcode, String owner, String name, String descriptor) {
            flush();
            super.visitFieldInsn(opcode, owner, name, descriptor);
        }

        @Override
        public void visitMethodInsn(int opcode, String owner, String name, String descriptor, boolean isInterface) {
            flush();
            super.visitMethodInsn(opcode, owner, name, descriptor, isInterface);
        }

        @Override
        public void visitInvokeDynamicInsn(String name, String descriptor, Handle bsm, Object... bsmArgs) {
            flush();
            super.visitInvokeDynamicInsn(name, descriptor, bsm, bsmArgs);
        }

        @Override
        public void visitJumpInsn(int opcode, Label label) {
            flush();
            super.visitJumpInsn(opcode, label);
        }

        @Override
        public void visitLdcInsn(Object value) {
            flush();
            super.visitLdcInsn(value);
        }

        @Override
        public void visitIincInsn(int var, int increment) {
            flush();
            super.visitIincInsn(var, increment);
        }

        @Override
        public void visitTableSwitchInsn(int min, int max, Label dflt, Label... labels) {
            flush();
            super.visitTableSwitchInsn(min, max, dflt, labels);
        }

        @Override
        public void visitLookupSwitchInsn(Label dflt, int[] keys, Label[] labels) {
            flush();
            super.visitLookupSwitchInsn(dflt, keys, labels);
        }

        @Override
        public void visitMultiANewArrayInsn(String descriptor, int numDimensions) {
            flush();
            super.visitMultiANewArrayInsn(descriptor, numDimensions);
        }

        @Override
        public void visitMaxs(int maxStack, int maxLocals) {
            super.visitMaxs(maxStack + 2, maxLocals);
        }
    }
}
