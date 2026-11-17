package org.example.loja;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Loja demo (espelha python/examples/loja). Rodar com o agente:
 * java -javaagent:glowtrace-agent.jar=packages=org.example.loja;sources=src/main/java -jar target/demo-loja.jar
 */
@SpringBootApplication
public class LojaApplication {
    public static void main(String[] args) {
        SpringApplication.run(LojaApplication.class, args);
    }
}
