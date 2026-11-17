package org.example.loja.model;

import java.util.ArrayList;
import java.util.List;

public class Pedido {
    private final String cliente;
    private final List<Item> itens;
    private final String cupom;
    private double total = 0.0;
    private String status = "novo";
    private final List<String> avisos = new ArrayList<>();

    public Pedido(String cliente, List<Item> itens, String cupom) {
        this.cliente = cliente;
        this.itens = itens == null ? new ArrayList<>() : itens;
        this.cupom = cupom;
    }

    public String getCliente() {
        return cliente;
    }

    public List<Item> getItens() {
        return itens;
    }

    public String getCupom() {
        return cupom;
    }

    public double getTotal() {
        return total;
    }

    public void setTotal(double total) {
        this.total = total;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public List<String> getAvisos() {
        return avisos;
    }
}
