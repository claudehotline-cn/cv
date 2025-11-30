package com.cv.cp.controller;

import com.cv.cp.config.AppProperties;
import com.cv.cp.logging.AuditLogger;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.URI;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.RequestEntity;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

@RestController
@RequestMapping("/api/agent")
public class AgentController {

  private final RestTemplate restTemplate = new RestTemplate();
  private final ObjectMapper objectMapper;
  private final AppProperties appProperties;

  public AgentController(ObjectMapper objectMapper, AppProperties appProperties) {
    this.objectMapper = objectMapper;
    this.appProperties = appProperties;
  }

  @PostMapping("/threads/{threadId}/invoke")
  public ResponseEntity<String> invokeThread(
      @PathVariable("threadId") String threadId,
      @RequestBody(required = false) String body) {
    String corrId = UUID.randomUUID().toString();
    String base = null;
    if (appProperties.getAgent() != null) {
      base = appProperties.getAgent().getBaseUrl();
    }
    if (base == null || base.isEmpty()) {
      base = System.getenv("CP_AGENT_BASE_URL");
    }
    if (base == null || base.isEmpty()) {
      base = "http://agent:8000";
    }
    String target = normalizeBase(base) + "/v1/agent/threads/" + threadId + "/invoke";
    String patchedBody = body;
    if (body != null && !body.isBlank()) {
      try {
        JsonNode root = objectMapper.readTree(body);
        if (root.isObject() && root.has("messages") && root.get("messages").isArray()) {
          JsonNode msgs = root.get("messages");
          if (msgs.isArray()) {
            var arr = (com.fasterxml.jackson.databind.node.ArrayNode) msgs;
            com.fasterxml.jackson.databind.node.ObjectNode sys = objectMapper.createObjectNode();
            sys.put("role", "system");
            sys.put(
                "content",
                "Agent 通过 ControlPlane 转发请求；请遵守上游系统约定的安全与资源限制。");
            arr.insert(0, sys);
            patchedBody = objectMapper.writeValueAsString(root);
          }
        }
      } catch (Exception ex) {
        patchedBody = body;
      }
    }
    Map<String, Object> auditPayload = new HashMap<>();
    auditPayload.put("thread_id", threadId);
    auditPayload.put("agent_base", base);
    // 尝试从请求体中提取 control 字段，补充审计信息（op/mode/confirm）
    if (patchedBody != null && !patchedBody.isBlank()) {
      try {
        JsonNode root = objectMapper.readTree(patchedBody);
        JsonNode control = root.get("control");
        if (control != null && control.isObject()) {
          if (control.hasNonNull("op")) {
            auditPayload.put("op", control.get("op").asText());
          }
          if (control.hasNonNull("mode")) {
            auditPayload.put("mode", control.get("mode").asText());
          }
          if (control.has("confirm")) {
            auditPayload.put("confirm", control.get("confirm").asBoolean(false));
          }
        }
      } catch (Exception ex) {
        // ignore parse errors for audit enrichment
      }
    }
    AuditLogger.log("agent.invoke.request", corrId, auditPayload);

    HttpHeaders headers = new HttpHeaders();
    headers.setContentType(MediaType.APPLICATION_JSON);
    RequestEntity<String> req =
        RequestEntity.post(URI.create(target))
            .headers(headers)
            .body(patchedBody != null ? patchedBody : "{}");
    try {
      ResponseEntity<String> resp = restTemplate.exchange(req, String.class);
      Map<String, Object> respAudit = new HashMap<>();
      respAudit.put("status", resp.getStatusCode().value());
      // 尝试从响应中提取 control_result 关键字段，用于审计
      String respBody = resp.getBody();
      if (respBody != null && !respBody.isBlank()) {
        try {
          JsonNode root = objectMapper.readTree(respBody);
          JsonNode cr = root.get("control_result");
          if (cr != null && cr.isObject()) {
            if (cr.hasNonNull("op")) {
              respAudit.put("op", cr.get("op").asText());
            }
            if (cr.hasNonNull("mode")) {
              respAudit.put("mode", cr.get("mode").asText());
            }
            if (cr.has("success")) {
              respAudit.put("success", cr.get("success").asBoolean(false));
            }
          }
        } catch (Exception ex) {
          // ignore parse errors for audit enrichment
        }
      }
      AuditLogger.log("agent.invoke.response", corrId, respAudit);
      return ResponseEntity.status(resp.getStatusCode()).body(resp.getBody());
    } catch (RestClientException ex) {
      Map<String, Object> respAudit = new HashMap<>();
      respAudit.put("status", 502);
      respAudit.put("error", ex.getMessage());
      AuditLogger.log("agent.invoke.error", corrId, respAudit);
      return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
          .body("{\"code\":\"BACKEND_ERROR\"}");
    }
  }

  private String normalizeBase(String base) {
    String s = base.trim();
    if (s.startsWith("http://")) {
      s = s.substring(7);
    } else if (s.startsWith("https://")) {
      s = s.substring(8);
    }
    int slash = s.indexOf('/');
    String hostPort = slash >= 0 ? s.substring(0, slash) : s;
    String prefix = slash >= 0 ? s.substring(slash) : "";
    if (prefix.isEmpty()) {
      prefix = "";
    }
    return "http://" + hostPort + prefix;
  }
}
