package com.cv.cp.controller;

import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.io.PrintWriter;
import java.util.HashMap;
import java.util.Map;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
public class EventsController {

  @GetMapping(
      path = "/events/stream",
      produces = MediaType.TEXT_EVENT_STREAM_VALUE)
  public void eventsStream(HttpServletResponse response) throws IOException {
    response.setStatus(HttpServletResponse.SC_OK);
    response.setContentType(MediaType.TEXT_EVENT_STREAM_VALUE);
    response.setHeader("Cache-Control", "no-cache");
    response.setHeader("Connection", "keep-alive");
    PrintWriter writer = response.getWriter();
    writer.write("event: init\n");
    writer.write("data:{}\n\n");
    writer.flush();
    for (int i = 0; i < 30; i++) {
      try {
        Thread.sleep(1000L);
      } catch (InterruptedException ex) {
        Thread.currentThread().interrupt();
        break;
      }
      writer.write(": keepalive\n\n");
      writer.flush();
    }
  }

  @GetMapping("/events/recent")
  public ResponseEntity<CpResponse<Map<String, Object>>> eventsRecent() {
    Map<String, Object> data = new HashMap<>();
    data.put("items", java.util.Collections.emptyList());
    data.put("next", 0);
    return ResponseEntity.ok(CpResponse.ok(data));
  }
}
