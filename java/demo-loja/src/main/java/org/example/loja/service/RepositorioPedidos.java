package org.example.loja.service;

import org.example.loja.model.Pedido;
import org.springframework.stereotype.Repository;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@Repository
public class RepositorioPedidos {
    private final Map<Integer, Pedido> db = new ConcurrentHashMap<>();

    public synchronized int salvar(Pedido pedido) {
        int pid = db.size() + 1;
        db.put(pid, pedido);
        return pid;
    }

    public Pedido buscar(int pid) {
        return db.get(pid);
    }
}
