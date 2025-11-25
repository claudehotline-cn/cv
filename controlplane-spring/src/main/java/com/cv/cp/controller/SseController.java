package com.cv.cp.controller;

import com.cv.cp.grpc.VideoSourceManagerClient;
import java.io.IOException;
import java.io.PrintWriter;
import java.util.Iterator;
import java.util.concurrent.CompletableFuture;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import vsm.v1.WatchStateReply;
import vsm.v1.SourceItem;

@RestController
@RequestMapping("/api")
public class SseController {

  private static final Logger log = LoggerFactory.getLogger(SseController.class);

  private final VideoSourceManagerClient vsmClient;

  public SseController(VideoSourceManagerClient vsmClient) {
    this.vsmClient = vsmClient;
  }

  @GetMapping(
      path = "/subscriptions/{id}/events",
      produces = MediaType.TEXT_EVENT_STREAM_VALUE)
  public SseEmitter subscriptionEvents(@PathVariable("id") String id) {
    SseEmitter emitter = new SseEmitter(15_000L);
    CompletableFuture.runAsync(
        () -> {
          try {
            String payload = "{\"id\":\"" + id + "\",\"phase\":\"ready\"}";
            emitter.send(SseEmitter.event().name("phase").data(payload));
            emitter.complete();
          } catch (IOException ex) {
            emitter.completeWithError(ex);
          }
        });
    return emitter;
  }

  @GetMapping(
      path = "/sources/watch_sse",
      produces = MediaType.TEXT_EVENT_STREAM_VALUE)
  public void sourcesWatch(HttpServletResponse response) throws IOException {
    response.setStatus(HttpServletResponse.SC_OK);
    response.setContentType(MediaType.TEXT_EVENT_STREAM_VALUE);
    response.setHeader("Cache-Control", "no-cache");
    response.setHeader("Connection", "keep-alive");
    PrintWriter writer = response.getWriter();
    writer.flush();

    boolean sent = false;
    try {
      Iterator<WatchStateReply> it = vsmClient.watchState(1000);
      long started = System.currentTimeMillis();
      while (it.hasNext() && System.currentTimeMillis() - started < 10_000L) {
        WatchStateReply reply = it.next();
        String payload = toJson(reply);
        writer.write("event: state\n");
        writer.write("data:" + payload + "\n\n");
        writer.flush();
        sent = true;
        break;
      }
    } catch (Exception ex) {
      log.warn("VSM WatchState failed, fallback to empty items", ex);
    }
    if (!sent) {
      writer.write("event: state\n");
      writer.write("data:{\"items\":[]}\n\n");
      writer.flush();
    }
  }

  private String toJson(WatchStateReply reply) {
    StringBuilder sb = new StringBuilder();
    sb.append("{\"items\":[");
    boolean first = true;
    for (SourceItem item : reply.getItemsList()) {
      if (!first) {
        sb.append(',');
      }
      first = false;
      sb.append('{');
      sb.append("\"attach_id\":\"").append(escape(item.getAttachId())).append('"');
      sb.append(",\"phase\":\"").append(escape(item.getPhase())).append('"');
      sb.append(",\"fps\":").append(item.getFps());
      if (!item.getProfile().isEmpty()) {
        sb.append(",\"profile\":\"").append(escape(item.getProfile())).append('"');
      }
      if (!item.getModelId().isEmpty()) {
        sb.append(",\"model_id\":\"").append(escape(item.getModelId())).append('"');
      }
      if (!item.getSourceUri().isEmpty()) {
        sb.append(",\"source_uri\":\"").append(escape(item.getSourceUri())).append('"');
      }
      sb.append('}');
    }
    sb.append("]}");
    return sb.toString();
  }

  private String escape(String value) {
    return value.replace("\\", "\\\\").replace("\"", "\\\"");
  }
}
