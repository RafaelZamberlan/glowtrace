package org.example.loja.api;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/** "Middleware" do demo: bloqueia /bloqueado e acrescenta X-Frame-Options. */
@Component
public class CabecalhosSeguranca extends OncePerRequestFilter {
    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        if (request.getRequestURI().startsWith("/bloqueado")) {
            response.setStatus(403);
            response.setContentType("application/json");
            response.getWriter().write("{\"detail\":\"bloqueado\"}");
            return;
        }
        response.setHeader("X-Frame-Options", "DENY");
        chain.doFilter(request, response);
    }
}
