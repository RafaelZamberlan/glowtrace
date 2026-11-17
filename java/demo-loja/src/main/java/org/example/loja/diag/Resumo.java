package org.example.loja.diag;

/** Casos de bytecode que já quebraram a instrumentação (regressão do Glowtrace). */
public record Resumo(String texto, String status) {

    /** new X(..., cond ? a : b): frame com objeto não inicializado no meio dos argumentos. */
    public static Resumo de(StringBuilder corpo, String motivo, String status) {
        return new Resumo(corpo.toString(), motivo.isEmpty() ? status : motivo);
    }

    /** cond ? new A() : new B(): o segundo `new` é alvo de salto. */
    public static Object umOuOutro(boolean flag) {
        Object x = flag ? new StringBuilder("a") : new java.util.ArrayList<String>();
        return x.getClass().getSimpleName();
    }

    /** new dentro de laço e de try/catch. */
    public static int varios(int n) {
        int total = 0;
        for (int i = 0; i < n; i++) {
            try {
                total += new Resumo(String.valueOf(i), i % 2 == 0 ? "par" : "impar").texto().length();
            } catch (RuntimeException e) {
                total = -1;
            }
        }
        return total;
    }
}
