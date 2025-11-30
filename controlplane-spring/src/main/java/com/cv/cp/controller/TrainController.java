package com.cv.cp.controller;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.URI;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

@RestController
@RequestMapping("/api/train")
public class TrainController {

  private final RestTemplate restTemplate = new RestTemplate();
  private final ObjectMapper objectMapper;

  public TrainController(ObjectMapper objectMapper) {
    this.objectMapper = objectMapper;
  }

  @PostMapping("/start")
  public ResponseEntity<String> start(@RequestBody(required = false) String body) {
    String base = trainerBase();
    if (base == null) {
      return ResponseEntity.status(HttpStatus.NOT_IMPLEMENTED)
          .body("{\"code\":\"TRAINER_UNAVAILABLE\"}");
    }
    String target = base + "/api/train/start";
    HttpHeaders headers = new HttpHeaders();
    headers.setContentType(MediaType.APPLICATION_JSON);
    HttpEntity<String> req = new HttpEntity<>(body != null ? body : "{}", headers);
    try {
      ResponseEntity<String> resp =
          restTemplate.postForEntity(URI.create(target), req, String.class);
      String patched = patchStartResponse(resp.getBody());
      return ResponseEntity.status(resp.getStatusCode())
          .body(patched != null ? patched : resp.getBody());
    } catch (RestClientException ex) {
      return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
          .body("{\"code\":\"BACKEND_ERROR\"}");
    }
  }

  @GetMapping("/status")
  public ResponseEntity<String> status(@RequestParam("id") String id) {
    String base = trainerBase();
    if (base == null) {
      return ResponseEntity.status(HttpStatus.NOT_IMPLEMENTED)
          .body("{\"code\":\"TRAINER_UNAVAILABLE\"}");
    }
    String target =
        base + "/api/train/status?id=" + url(id);
    try {
      ResponseEntity<String> resp =
          restTemplate.getForEntity(URI.create(target), String.class);
      return ResponseEntity.status(resp.getStatusCode()).body(resp.getBody());
    } catch (RestClientException ex) {
      return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
          .body("{\"code\":\"BACKEND_ERROR\"}");
    }
  }

  @GetMapping("/list")
  public ResponseEntity<String> list() {
    String base = trainerBase();
    if (base == null) {
      return ResponseEntity.status(HttpStatus.NOT_IMPLEMENTED)
          .body("{\"code\":\"TRAINER_UNAVAILABLE\"}");
    }
    String target = base + "/api/train/list";
    try {
      ResponseEntity<String> resp =
          restTemplate.getForEntity(URI.create(target), String.class);
      return ResponseEntity.status(resp.getStatusCode()).body(resp.getBody());
    } catch (RestClientException ex) {
      return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
          .body("{\"code\":\"BACKEND_ERROR\"}");
    }
  }

  @PostMapping("/deploy")
  public ResponseEntity<String> deploy(@RequestBody(required = false) String body) {
    String base = trainerBase();
    if (base == null) {
      return ResponseEntity.status(HttpStatus.NOT_IMPLEMENTED)
          .body("{\"code\":\"TRAINER_UNAVAILABLE\"}");
    }
    String target = base + "/api/train/deploy";
    HttpHeaders headers = new HttpHeaders();
    headers.setContentType(MediaType.APPLICATION_JSON);
    HttpEntity<String> req = new HttpEntity<>(body != null ? body : "{}", headers);
    try {
      ResponseEntity<String> resp =
          restTemplate.postForEntity(URI.create(target), req, String.class);
      return ResponseEntity.status(resp.getStatusCode()).body(resp.getBody());
    } catch (RestClientException ex) {
      return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
          .body("{\"code\":\"BACKEND_ERROR\"}");
    }
  }

  @GetMapping("/artifacts")
  public ResponseEntity<String> artifacts(
      @RequestParam("job") String job) {
    String base = trainerBase();
    if (base == null) {
      return ResponseEntity.status(HttpStatus.NOT_IMPLEMENTED)
          .body("{\"code\":\"TRAINER_UNAVAILABLE\"}");
    }
    String target =
        base + "/api/train/artifacts?job=" + url(job);
    try {
      ResponseEntity<String> resp =
          restTemplate.getForEntity(URI.create(target), String.class);
      return ResponseEntity.status(resp.getStatusCode()).body(resp.getBody());
    } catch (RestClientException ex) {
      return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
          .body("{\"code\":\"BACKEND_ERROR\"}");
    }
  }

  @GetMapping("/artifacts/download")
  public ResponseEntity<byte[]> artifactsDownload(
      @RequestParam("job") String job,
      @RequestParam("name") String name) {
    String base = trainerBase();
    if (base == null) {
      return ResponseEntity.status(HttpStatus.NOT_IMPLEMENTED)
          .body("{\"code\":\"TRAINER_UNAVAILABLE\"}".getBytes(StandardCharsets.UTF_8));
    }
    String target =
        base
            + "/api/train/artifacts/download?job="
            + url(job)
            + "&name="
            + url(name);
    try {
      ResponseEntity<byte[]> resp =
          restTemplate.getForEntity(URI.create(target), byte[].class);
      HttpHeaders headers = new HttpHeaders();
      MediaType ctype = resp.getHeaders().getContentType();
      if (ctype != null) {
        headers.setContentType(ctype);
      } else {
        headers.setContentType(MediaType.APPLICATION_OCTET_STREAM);
      }
      return new ResponseEntity<>(resp.getBody(), headers, resp.getStatusCode());
    } catch (RestClientException ex) {
      return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
          .body("{\"code\":\"BACKEND_ERROR\"}".getBytes(StandardCharsets.UTF_8));
    }
  }

  private String trainerBase() {
    String base = System.getenv("CP_TRAINER_BASE_URL");
    if (base == null || base.isEmpty()) {
      return null;
    }
    String s = base.trim();
    if (s.endsWith("/")) {
      s = s.substring(0, s.length() - 1);
    }
    return s;
  }

  private String patchStartResponse(String body) {
    if (body == null || body.isEmpty()) {
      return body;
    }
    try {
      JsonNode root = objectMapper.readTree(body);
      if (root.has("data") && root.get("data").isObject()) {
        JsonNode data = root.get("data");
        if (data.has("job") && data.get("job").isTextual()) {
          String id = data.get("job").asText();
          ((com.fasterxml.jackson.databind.node.ObjectNode) data)
              .put("events", "/api/train/events?id=" + id);
        }
      }
      return objectMapper.writeValueAsString(root);
    } catch (Exception ex) {
      return body;
    }
  }

  private String url(String v) {
    return URLEncoder.encode(v, StandardCharsets.UTF_8);
  }
}
