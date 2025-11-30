package com.cv.cp.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.web.filter.OncePerRequestFilter;

public class BearerTokenFilter extends OncePerRequestFilter {

  private static final Logger log = LoggerFactory.getLogger(BearerTokenFilter.class);

  private final String expectedToken;

  public BearerTokenFilter(String expectedToken) {
    this.expectedToken = expectedToken;
  }

  @Override
  protected void doFilterInternal(
      HttpServletRequest request,
      HttpServletResponse response,
      FilterChain filterChain) throws ServletException, IOException {
    if (expectedToken == null || expectedToken.isEmpty()) {
      filterChain.doFilter(request, response);
      return;
    }
    String auth = request.getHeader("Authorization");
    if (auth == null || !auth.startsWith("Bearer ")) {
      response.setStatus(HttpStatus.UNAUTHORIZED.value());
      response.setContentType("application/json");
      response.getWriter().write("{\"code\":\"UNAUTHENTICATED\",\"msg\":\"missing bearer token\"}");
      response.getWriter().flush();
      return;
    }
    String token = auth.substring("Bearer ".length());
    if (!expectedToken.equals(token)) {
      log.warn("Invalid bearer token for path {}", request.getRequestURI());
      response.setStatus(HttpStatus.FORBIDDEN.value());
      response.setContentType("application/json");
      response.getWriter().write("{\"code\":\"PERMISSION_DENIED\",\"msg\":\"invalid bearer token\"}");
      response.getWriter().flush();
      return;
    }
    filterChain.doFilter(request, response);
  }
}

