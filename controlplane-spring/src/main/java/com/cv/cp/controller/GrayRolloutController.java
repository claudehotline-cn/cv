package com.cv.cp.controller;

import com.cv.cp.service.GrayRolloutService;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.io.PrintWriter;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/deploy/gray")
public class GrayRolloutController {

  private final GrayRolloutService grayRolloutService;
  private final ObjectMapper objectMapper;

  public GrayRolloutController(GrayRolloutService grayRolloutService, ObjectMapper objectMapper) {
    this.grayRolloutService = grayRolloutService;
    this.objectMapper = objectMapper;
  }

  @PostMapping("/start")
  public ResponseEntity<CpResponse<Map<String, Object>>> start(
      @RequestBody(required = false) String body) {
    if (body == null || body.isBlank()) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
    Map<String, Object> payload;
    try {
      payload = objectMapper.readValue(body, Map.class);
    } catch (IOException ex) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
    try {
      Map<String, Object> data = grayRolloutService.start(payload);
      return ResponseEntity.status(HttpStatus.ACCEPTED)
          .body(new CpResponse<>("ACCEPTED", null, data));
    } catch (IllegalArgumentException ex) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(new CpResponse<>("INVALID_ARGUMENT", ex.getMessage(), null));
    }
  }

  @GetMapping("/status")
  public ResponseEntity<CpResponse<Map<String, Object>>> status(
      @RequestParam("id") String id) {
    Map<String, Object> out = grayRolloutService.status(id);
    if (out == null) {
      return ResponseEntity.status(HttpStatus.NOT_FOUND)
          .body(new CpResponse<>("NOT_FOUND", null, null));
    }
    return ResponseEntity.ok(new CpResponse<>("OK", null, (Map<String, Object>) out.get("data")));
  }

  @GetMapping(
      path = "/events",
      produces = MediaType.TEXT_EVENT_STREAM_VALUE)
  public void events(
      @RequestParam("id") String id,
      HttpServletResponse response) throws IOException {
    response.setStatus(HttpServletResponse.SC_OK);
    response.setContentType(MediaType.TEXT_EVENT_STREAM_VALUE);
    response.setHeader("Cache-Control", "no-cache");
    response.setHeader("Connection", "keep-alive");
    PrintWriter writer = response.getWriter();
    int idx = 0;
    long lastKeep = System.currentTimeMillis();
    while (true) {
      List<String> batch = grayRolloutService.consumeEvents(id, idx);
      if (batch == null) {
        writer.write("event: error\n");
        writer.write("data:{\"code\":\"NOT_FOUND\"}\n\n");
        writer.flush();
        break;
      }
      if (!batch.isEmpty()) {
        for (String line : batch) {
          try {
            Map<String, Object> j = objectMapper.readValue(line, Map.class);
            String kind = (String) j.getOrDefault("kind", "message");
            Object data = j.get("data");
            String payload = objectMapper.writeValueAsString(data);
            writer.write("event: " + kind + "\n");
            writer.write("data:" + payload + "\n\n");
          } catch (Exception ex) {
            // ignore this event
          }
        }
        writer.flush();
        idx += batch.size();
        lastKeep = System.currentTimeMillis();
      }
      if (System.currentTimeMillis() - lastKeep > 8000L) {
        writer.write(": keepalive\n\n");
        writer.flush();
        lastKeep = System.currentTimeMillis();
      }
      try {
        Thread.sleep(200L);
      } catch (InterruptedException ex) {
        Thread.currentThread().interrupt();
        break;
      }
    }
  }
}

