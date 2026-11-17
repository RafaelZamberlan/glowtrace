package org.example.loja.service;

public class EstoqueInsuficiente extends RuntimeException {
    public EstoqueInsuficiente(String message) {
        super(message);
    }
}
