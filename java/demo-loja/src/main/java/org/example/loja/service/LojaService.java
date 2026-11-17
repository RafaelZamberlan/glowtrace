package org.example.loja.service;

import org.example.loja.model.Item;
import org.example.loja.model.Pedido;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Serviços da loja demo - cheios de ramificações e laços de propósito. */
@Service
public class LojaService {
    private static final Logger log = LoggerFactory.getLogger(LojaService.class);

    // "notebook" permite exercitar o pagamento recusado (valor > 1000)
    static final Map<String, Integer> ESTOQUE = Map.of("camiseta", 10, "caneca", 0, "boné", 3, "notebook", 5);
    static final Map<String, Double> PRECOS = Map.of("camiseta", 59.9, "caneca", 29.9, "boné", 39.9, "notebook", 4599.0);

    private final RepositorioPedidos repo;

    public LojaService(RepositorioPedidos repo) {
        this.repo = repo;
    }

    public List<String> validarItens(List<Item> itens) {
        List<String> erros = new ArrayList<>();
        for (Item item : itens) {
            String nome = item.produto();
            int qtd = item.qtd() == null ? 1 : item.qtd();
            if (!ESTOQUE.containsKey(nome)) {
                erros.add("produto inexistente: " + nome);
                continue;
            }
            if (qtd <= 0) {
                erros.add("quantidade inválida: " + nome);
            } else if (ESTOQUE.get(nome) < qtd) {
                erros.add("sem estoque: " + nome);
            }
        }
        return erros;
    }

    public double aplicarCupom(double total, String cupom) {
        if (cupom == null) {
            return total;
        }
        double desconto;
        switch (cupom) {
            case "PRIMEIRA":
                desconto = 0.10;
                break;
            case "VIP":
                desconto = 0.25;
                break;
            default:
                log.info("cupom desconhecido {}", cupom);
                return total;
        }
        return Math.round(total * (1 - desconto) * 100) / 100.0;
    }

    public double calcularTotal(Pedido pedido) {
        double total = 0.0;
        for (Item item : pedido.getItens()) {
            double preco = PRECOS.get(item.produto());
            total += preco * (item.qtd() == null ? 1 : item.qtd());
        }
        if (total > 200) {
            pedido.getAvisos().add("frete grátis");
        } else {
            total += 15.0;
        }
        return aplicarCupom(total, pedido.getCupom());
    }

    public Map<String, Object> cobrar(String cliente, double valor) {
        if (valor > 1000) {
            throw new IllegalStateException("limite do cartão excedido");
        }
        Map<String, Object> pagamento = new LinkedHashMap<>();
        pagamento.put("aprovado", true);
        pagamento.put("valor", valor);
        pagamento.put("cliente", cliente);
        return pagamento;
    }

    public Map<String, Object> criarPedido(Pedido pedido) {
        List<String> erros = validarItens(pedido.getItens());
        if (!erros.isEmpty()) {
            throw new EstoqueInsuficiente(String.join("; ", erros));
        }
        pedido.setTotal(calcularTotal(pedido));
        Map<String, Object> pagamento;
        try {
            pagamento = cobrar(pedido.getCliente(), pedido.getTotal());
        } catch (IllegalStateException exc) {
            pedido.setStatus("recusado");
            Map<String, Object> recusa = new LinkedHashMap<>();
            recusa.put("status", pedido.getStatus());
            recusa.put("motivo", exc.getMessage());
            return recusa;
        }
        pedido.setStatus(Boolean.TRUE.equals(pagamento.get("aprovado")) ? "pago" : "pendente");
        int pid = repo.salvar(pedido);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", pid);
        out.put("status", pedido.getStatus());
        out.put("total", pedido.getTotal());
        out.put("avisos", pedido.getAvisos());
        return out;
    }

    public Map<String, Object> relatorio(int limite) {
        int vistos = 0;
        Map<String, Integer> resumo = new LinkedHashMap<>();
        while (vistos < limite) {
            vistos++;
            Pedido pedido = repo.buscar(vistos);
            if (pedido == null) {
                break;
            }
            resumo.merge(pedido.getStatus(), 1, Integer::sum);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("analisados", vistos);
        out.put("por_status", resumo);
        return out;
    }
}
