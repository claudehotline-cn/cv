package com.cv.cp.config;

import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.concurrent.TimeUnit;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
public class HttpMetricsFilter extends OncePerRequestFilter {

  private final MeterRegistry meterRegistry;

  public HttpMetricsFilter(MeterRegistry meterRegistry) {
    this.meterRegistry = meterRegistry;
  }

  @Override
  protected void doFilterInternal(
      HttpServletRequest request,
      HttpServletResponse response,
      FilterChain filterChain) throws ServletException, IOException {
    long start = System.nanoTime();
    try {
      filterChain.doFilter(request, response);
    } finally {
      long duration = System.nanoTime() - start;
      String path = request.getRequestURI();
      String method = request.getMethod();
      String status = Integer.toString(response.getStatus());
      Timer.builder("cp.http.server")
          .tag("path", path)
          .tag("method", method)
          .tag("status", status)
          .register(meterRegistry)
          .record(duration, TimeUnit.NANOSECONDS);
    }
  }
}

