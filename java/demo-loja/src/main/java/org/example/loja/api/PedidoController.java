package org.example.loja.api;

import org.example.loja.model.NovoPedido;
import org.example.loja.model.Pedido;
import org.example.loja.service.EstoqueInsuficiente;
import org.example.loja.service.LojaService;
import org.example.loja.service.RepositorioPedidos;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
public class PedidoController {
    private final LojaService loja;
    private final RepositorioPedidos repo;

    public PedidoController(LojaService loja, RepositorioPedidos repo) {
        this.loja = loja;
        this.repo = repo;
    }

    String usuarioAtual(String authorization) {
        if (authorization == null || authorization.isBlank()) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "sem token");
        }
        if (!authorization.startsWith("Bearer ")) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "formato inválido");
        }
        String usuario = authorization.substring("Bearer ".length()).split("\\.")[0];
        return usuario.isEmpty() ? "anon" : usuario;
    }

    @PostMapping("/pedidos")
    public Map<String, Object> criarPedido(@RequestBody NovoPedido body,
                                           @RequestHeader(value = "Authorization", required = false) String authorization) {
        String usuario = usuarioAtual(authorization);
        Pedido pedido = new Pedido(body.cliente(), body.itens(), body.cupom());
        try {
            return loja.criarPedido(pedido);
        } catch (EstoqueInsuficiente exc) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, exc.getMessage() + " (" + usuario + ")");
        }
    }

    @GetMapping("/pedidos/{pid}")
    public Map<String, Object> obterPedido(@PathVariable int pid) {
        Pedido pedido = repo.buscar(pid);
        if (pedido == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "pedido não encontrado");
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("cliente", pedido.getCliente());
        out.put("status", pedido.getStatus());
        out.put("total", pedido.getTotal());
        return out;
    }

    @GetMapping("/relatorio")
    public Map<String, Object> relatorio(@RequestParam(defaultValue = "10") int limite) {
        return loja.relatorio(limite);
    }

    @GetMapping("/diagnostico")
    public Map<String, Object> diagnostico(@RequestParam(defaultValue = "") String motivo) {
        org.example.loja.diag.Resumo r = org.example.loja.diag.Resumo.de(new StringBuilder("corpo"), motivo, "ok");
        return Map.of("resumo", r.status(), "tipo", org.example.loja.diag.Resumo.umOuOutro(motivo.isEmpty()),
                "varios", org.example.loja.diag.Resumo.varios(3));
    }

    @GetMapping("/quebra")
    public int quebra() {
        Map<String, Integer> dados = Map.of("a", 1);
        return dados.get("b") * 2; // NullPointerException -> 500
    }
}
