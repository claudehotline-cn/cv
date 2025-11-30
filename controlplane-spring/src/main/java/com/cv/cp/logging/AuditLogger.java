package com.cv.cp.logging;

import java.time.Instant;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public final class AuditLogger {

  private static final Logger log = LoggerFactory.getLogger("cp.audit");

  private AuditLogger() {}

  public static void log(String event, String correlationId, Map<String, Object> payload) {
    try {
      StringBuilder sb = new StringBuilder();
      sb.append("{\"ts_ms\":").append(Instant.now().toEpochMilli());
      sb.append(",\"level\":\"INFO\"");
      sb.append(",\"event\":\"").append(escape(event)).append("\"");
      sb.append(",\"corr_id\":");
      if (correlationId != null) {
        sb.append("\"").append(escape(correlationId)).append("\"");
      } else {
        sb.append("null");
      }
      if (payload != null) {
        for (Map.Entry<String, Object> e : payload.entrySet()) {
          sb.append(",\"").append(escape(e.getKey())).append("\":\"")
              .append(escape(String.valueOf(e.getValue()))).append("\"");
        }
      }
      sb.append("}");
      log.info(sb.toString());
    } catch (Exception ignored) {
      // do not break business flow on audit failure
    }
  }

  private static String escape(String v) {
    return v.replace("\\", "\\\\").replace("\"", "\\\"");
  }
}

