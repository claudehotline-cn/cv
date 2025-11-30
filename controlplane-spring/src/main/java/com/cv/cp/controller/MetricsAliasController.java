package com.cv.cp.controller;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestTemplate;

@RestController
public class MetricsAliasController {

  private final RestTemplate restTemplate;

  public MetricsAliasController(RestTemplateBuilder builder) {
    this.restTemplate = builder.build();
  }

  @GetMapping("/metrics")
  public ResponseEntity<String> metrics(HttpServletRequest request) {
    String scheme = request.getScheme();
    String host = request.getServerName();
    int port = request.getServerPort();
    String base = scheme + "://" + host + ":" + port;
    String url = base + "/actuator/prometheus";
    String body = restTemplate.getForObject(url, String.class);
    return ResponseEntity.ok(body != null ? body : "");
  }
}

