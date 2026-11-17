package org.example.loja.model;

import java.util.List;

/** Corpo do POST /pedidos (cpf e senhaCartao existem para testar a redação de dados sensíveis). */
public record NovoPedido(String cliente, String cpf, String senhaCartao, List<Item> itens, String cupom) {
}
