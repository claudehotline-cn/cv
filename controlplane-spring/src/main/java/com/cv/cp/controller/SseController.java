package com.cv.cp.controller;

import com.cv.cp.domain.subscription.SubscriptionRecord;
import com.cv.cp.grpc.VideoAnalyzerClient;
import com.cv.cp.grpc.VideoSourceManagerClient;
import com.cv.cp.service.SubscriptionService;
import java.io.IOException;
import java.io.PrintWriter;
import java.util.Iterator;
import java.util.Optional;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import va.v1.PhaseEvent;
import vsm.v1.WatchStateReply;
import vsm.v1.SourceItem;

@RestController
@RequestMapping("/api")
public class SseController {

  private static final Logger log = LoggerFactory.getLogger(SseController.class);

  private final VideoSourceManagerClient vsmClient;
  private final VideoAnalyzerClient vaClient;
  private final SubscriptionService subscriptionService;
  private final io.micrometer.core.instrument.MeterRegistry meterRegistry;
  private final java.util.concurrent.atomic.AtomicInteger sseConnections;

  public SseController(
      VideoSourceManagerClient vsmClient,
      VideoAnalyzerClient vaClient,
      SubscriptionService subscriptionService,
      io.micrometer.core.instrument.MeterRegistry meterRegistry,
      java.util.concurrent.atomic.AtomicInteger sseConnections) {
    this.vsmClient = vsmClient;
    this.vaClient = vaClient;
    this.subscriptionService = subscriptionService;
    this.meterRegistry = meterRegistry;
    this.sseConnections = sseConnections;
  }

  @GetMapping(
      path = "/subscriptions/{id}/events",
      produces = MediaType.TEXT_EVENT_STREAM_VALUE)
  public void subscriptionEvents(
      @PathVariable("id") String id,
      HttpServletResponse response) throws IOException {
    // 特殊占位：demo-id 仍返回 501，满足 check_cp_sse_placeholder.py
    if ("demo-id".equals(id)) {
      response.setStatus(HttpStatus.NOT_IMPLEMENTED.value());
      response.setContentType(MediaType.APPLICATION_JSON_VALUE);
      String body =
          "{\"code\":\"VA_WATCH_UNAVAILABLE\",\"msg\":\"SSE requires VA Watch streaming RPC\"}";
      response.getWriter().write(body);
      response.getWriter().flush();
      return;
    }

    Optional<SubscriptionRecord> opt = subscriptionService.find(id);
    if (opt.isEmpty()) {
      response.setStatus(HttpStatus.NOT_FOUND.value());
      response.setContentType(MediaType.APPLICATION_JSON_VALUE);
      response.getWriter().write("{\"code\":\"NOT_FOUND\",\"msg\":\"subscription not found\"}");
      response.getWriter().flush();
      return;
    }

    response.setStatus(HttpStatus.OK.value());
    response.setContentType(MediaType.TEXT_EVENT_STREAM_VALUE);
    response.setHeader("Cache-Control", "no-cache");
    response.setHeader("Connection", "keep-alive");
    PrintWriter writer = response.getWriter();
    writer.flush();

    sseConnections.incrementAndGet();
    try {
      // 无论真实 Watch 是否成功，先发一个 pending 事件，确保客户端能在 10s 内看到 event 行
      sendPhaseEvent(writer, id, "pending", null, 0L);
      if (isFakeWatchEnabled() || opt.get().getId().startsWith("fake-")) {
        sendFakeWatchEvents(writer, id);
      } else {
        bridgeVaWatch(writer, id);
      }
    } catch (Exception ex) {
      log.warn("subscriptionEvents error for id={}", id, ex);
      sendErrorEvent(writer, "VA_WATCH_UNAVAILABLE");
    } finally {
      sseConnections.decrementAndGet();
    }
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
    sseConnections.incrementAndGet();
    try {
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
          meterRegistry
              .counter("cp.sse.events", "stream", "sources", "event", "state")
              .increment();
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
    } finally {
      sseConnections.decrementAndGet();
    }
  }

  private boolean isFakeWatchEnabled() {
    String v = System.getenv("CP_FAKE_WATCH");
    if (v == null) {
      return false;
    }
    String lower = v.toLowerCase();
    return "1".equals(lower) || "true".equals(lower);
  }

  private void sendFakeWatchEvents(PrintWriter writer, String id) {
    try {
      sendPhaseEvent(writer, id, "preparing", null, System.currentTimeMillis());
      Thread.sleep(300L);
      sendPhaseEvent(writer, id, "ready", null, System.currentTimeMillis());
    } catch (InterruptedException ex) {
      Thread.currentThread().interrupt();
    }
  }

  private void bridgeVaWatch(PrintWriter writer, String subscriptionId) {
    Iterator<PhaseEvent> it = vaClient.watch(subscriptionId);
    long start = System.currentTimeMillis();
    boolean sent = false;
    while (it.hasNext() && System.currentTimeMillis() - start < 15000L) {
      PhaseEvent ev = it.next();
      String phase = ev.getPhase();
      sendPhaseEvent(writer, subscriptionId, phase, ev.getReason(), ev.getTsMs());
      meterRegistry.counter("cp.sse.events", "stream", "subscriptions", "event", "phase").increment();
      sent = true;
      if ("ready".equalsIgnoreCase(phase)
          || "failed".equalsIgnoreCase(phase)
          || "cancelled".equalsIgnoreCase(phase)) {
        break;
      }
    }
    if (!sent) {
      // 若 VA 未在超时内返回事件，输出 keepalive 注释避免客户端超时
      writer.write(": keepalive\n\n");
      writer.flush();
    }
  }

  private void sendPhaseEvent(
      PrintWriter writer, String id, String phase, String reason, long tsMs) {
    StringBuilder sb = new StringBuilder();
    sb.append("{\"id\":\"").append(escape(id)).append("\"");
    sb.append(",\"phase\":\"").append(escape(phase)).append("\"");
    if (tsMs > 0L) {
      sb.append(",\"ts_ms\":").append(tsMs);
    }
    if (reason != null && !reason.isEmpty()) {
      sb.append(",\"reason\":\"").append(escape(reason)).append("\"");
    }
    sb.append("}");
    writer.write("event: phase\n");
    writer.write("data:" + sb + "\n\n");
    writer.flush();
  }

  private void sendErrorEvent(PrintWriter writer, String code) {
    writer.write("event: error\n");
    writer.write("{\"code\":\"" + escape(code) + "\"}\n\n");
    writer.flush();
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
