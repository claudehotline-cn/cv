package com.cv.cp.controller;

import jakarta.servlet.ServletOutputStream;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/train")
public class TrainEventsController {

  @GetMapping(
      path = "/events",
      produces = MediaType.TEXT_EVENT_STREAM_VALUE)
  public void trainEvents(
      @RequestParam("id") String id,
      HttpServletResponse response) throws IOException {
    String base = System.getenv("CP_TRAINER_BASE_URL");
    if (base == null || base.isEmpty()) {
      // fall back to simple SSE error
      response.setStatus(HttpServletResponse.SC_OK);
      response.setContentType(MediaType.TEXT_EVENT_STREAM_VALUE);
      ServletOutputStream out = response.getOutputStream();
      out.write("event: error\n".getBytes(StandardCharsets.UTF_8));
      out.write("data:{\"code\":\"TRAINER_UNAVAILABLE\"}\n\n".getBytes(StandardCharsets.UTF_8));
      out.flush();
      return;
    }
    String urlStr =
        base.replaceAll("/+$", "")
            + "/api/train/events?id="
            + URLEncoder.encode(id, StandardCharsets.UTF_8);
    HttpURLConnection conn = null;
    try {
      URL url = new URL(urlStr);
      conn = (HttpURLConnection) url.openConnection();
      conn.setRequestMethod("GET");
      conn.setRequestProperty("Accept", "text/event-stream");
      conn.setDoInput(true);
      conn.connect();

      int code = conn.getResponseCode();
      InputStream in =
          code >= 200 && code < 300 ? conn.getInputStream() : conn.getErrorStream();
      if (in == null) {
        response.setStatus(HttpServletResponse.SC_OK);
        response.setContentType(MediaType.TEXT_EVENT_STREAM_VALUE);
        ServletOutputStream out = response.getOutputStream();
        out.write("event: error\n".getBytes(StandardCharsets.UTF_8));
        out.write("data:{\"code\":\"TRAINER_UNAVAILABLE\"}\n\n".getBytes(StandardCharsets.UTF_8));
        out.flush();
        return;
      }
      response.setStatus(HttpServletResponse.SC_OK);
      response.setContentType(MediaType.TEXT_EVENT_STREAM_VALUE);
      response.setHeader("Cache-Control", "no-cache");
      response.setHeader("Connection", "keep-alive");
      ServletOutputStream out = response.getOutputStream();
      byte[] buf = new byte[4096];
      int n;
      while ((n = in.read(buf)) > 0) {
        out.write(buf, 0, n);
        out.flush();
      }
    } catch (Exception ex) {
      response.setStatus(HttpServletResponse.SC_OK);
      response.setContentType(MediaType.TEXT_EVENT_STREAM_VALUE);
      ServletOutputStream out = response.getOutputStream();
      out.write("event: error\n".getBytes(StandardCharsets.UTF_8));
      out.write("data:{\"code\":\"TRAINER_UNAVAILABLE\"}\n\n".getBytes(StandardCharsets.UTF_8));
      out.flush();
    } finally {
      if (conn != null) {
        conn.disconnect();
      }
    }
  }
}

