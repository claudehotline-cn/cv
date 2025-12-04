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
import org.springframework.web.bind.annotation.GetMapping;
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

  // 与 C++ 版 controlplane 中的 kAgentSystemPrompt 保持语义一致：
  // 在 CP 层为每个 /api/agent/threads/{id}/invoke 请求注入统一的系统提示。
  private static final String AGENT_SYSTEM_PROMPT =
      "你是 CV 项目的控制平面智能 Agent，职责是协助用户安全地查看与管理视频分析管线（pipeline）、查询系统状态，以及根据项目文档回答问题。\n"
          + "\n"
          + "【总体原则】\n"
          + "- 优先使用真实系统接口（控制平面和后端工具）获取信息，而不是凭经验想象。\n"
          + "- 涉及删除、热切换、drain 等高危操作时，必须先给出变更计划和影响分析，仅在用户再次明确确认后才执行。\n"
          + "- 所有后端访问都通过控制平面提供的能力完成，你不需要也不能绕过控制平面直接访问其他组件。\n"
          + "\n"
          + "【能力概览】\n"
          + "- 管线只读查询：列出当前已配置的 pipelines（名称、graph_id、默认模型 ID 等），查询指定 pipeline 在 VA 中的运行状态与指标（phase/FPS/processed_frames 等）。\n"
          + "- 规划能力（plan / dry-run）：在删除、调整配置、drain、热切换之前，生成包含当前状态和目标状态的计划与 diff，不做实际修改，用于人机协同确认。\n"
          + "- 高危执行能力：在用户确认后，真实执行删除、drain、热切换等操作；执行前后都要明确说明影响与结果。\n"
          + "- 文档检索：基于项目文档知识库检索接口规范、设计说明、测试策略等，再据此回答问题。\n"
          + "\n"
          + "【使用约束】\n"
          + "- 用户不会告诉你具体的工具名称，你也不应该要求用户“调用某个工具”，而是根据自然语言需求自行选择合适的能力。\n"
          + "- 当用户第一次提出删除/切换/停止类请求时，只生成计划（包括影响面和风险），不要立刻执行。\n"
          + "- 只有在你给出计划之后，用户用自然语言明确表示“确认按这个计划执行”“可以执行删除/切换/drain”等时，才可以调用高危执行能力。\n"
          + "- 当问题是“当前有哪些 / 某个 pipeline 现在怎样”的实时状态问题时，应通过只读查询获取真实数据；当问题是“接口/协议/设计”的文档问题时，应优先检索项目文档。\n"
          + "\n"
          + "在整个对话过程中，请遵守上述原则，自主选择和组合你已有的能力为用户提供帮助。不要臆造不存在的 pipeline、接口或字段，如信息不足，请如实说明并给出可行的下一步建议。\n";

  private final RestTemplate restTemplate = new RestTemplate();
  private final ObjectMapper objectMapper;
  private final AppProperties appProperties;

  public AgentController(ObjectMapper objectMapper, AppProperties appProperties) {
    this.objectMapper = objectMapper;
    this.appProperties = appProperties;
  }

  private String resolveAgentBase() {
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
    return normalizeBase(base);
  }

  @GetMapping("/threads")
  public ResponseEntity<String> listThreads() {
    String corrId = UUID.randomUUID().toString();
    String base = resolveAgentBase();
    String target = base + "/v1/agent/threads";

    Map<String, Object> auditPayload = new HashMap<>();
    auditPayload.put("agent_base", base);
    AuditLogger.log("agent.threads.request", corrId, auditPayload);

    try {
      ResponseEntity<String> resp = restTemplate.getForEntity(URI.create(target), String.class);
      Map<String, Object> respAudit = new HashMap<>();
      respAudit.put("status", resp.getStatusCode().value());
      AuditLogger.log("agent.threads.response", corrId, respAudit);
      return ResponseEntity.status(resp.getStatusCode()).body(resp.getBody());
    } catch (RestClientException ex) {
      Map<String, Object> respAudit = new HashMap<>();
      respAudit.put("status", 502);
      respAudit.put("error", ex.getMessage());
      AuditLogger.log("agent.threads.error", corrId, respAudit);
      return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
          .body("{\"code\":\"BACKEND_ERROR\"}");
    }
  }

  @GetMapping("/threads/{threadId}/summary")
  public ResponseEntity<String> getThreadSummary(@PathVariable("threadId") String threadId) {
    String corrId = UUID.randomUUID().toString();
    String base = resolveAgentBase();
    String target = base + "/v1/agent/threads/" + threadId + "/summary";

    Map<String, Object> auditPayload = new HashMap<>();
    auditPayload.put("thread_id", threadId);
    auditPayload.put("agent_base", base);
    AuditLogger.log("agent.thread.summary.request", corrId, auditPayload);

    try {
      ResponseEntity<String> resp = restTemplate.getForEntity(URI.create(target), String.class);
      Map<String, Object> respAudit = new HashMap<>();
      respAudit.put("status", resp.getStatusCode().value());
      AuditLogger.log("agent.thread.summary.response", corrId, respAudit);
      return ResponseEntity.status(resp.getStatusCode()).body(resp.getBody());
    } catch (RestClientException ex) {
      Map<String, Object> respAudit = new HashMap<>();
      respAudit.put("status", 502);
      respAudit.put("error", ex.getMessage());
      AuditLogger.log("agent.thread.summary.error", corrId, respAudit);
      return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
          .body("{\"code\":\"BACKEND_ERROR\"}");
    }
  }

  @GetMapping("/stats")
  public ResponseEntity<String> getAgentStats() {
    String corrId = UUID.randomUUID().toString();
    String base = resolveAgentBase();
    String target = base + "/v1/agent/stats";

    Map<String, Object> auditPayload = new HashMap<>();
    auditPayload.put("agent_base", base);
    AuditLogger.log("agent.stats.request", corrId, auditPayload);

    try {
      ResponseEntity<String> resp = restTemplate.getForEntity(URI.create(target), String.class);
      Map<String, Object> respAudit = new HashMap<>();
      respAudit.put("status", resp.getStatusCode().value());
      AuditLogger.log("agent.stats.response", corrId, respAudit);
      return ResponseEntity.status(resp.getStatusCode()).body(resp.getBody());
    } catch (RestClientException ex) {
      Map<String, Object> respAudit = new HashMap<>();
      respAudit.put("status", 502);
      respAudit.put("error", ex.getMessage());
      AuditLogger.log("agent.stats.error", corrId, respAudit);
      return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
          .body("{\"code\":\"BACKEND_ERROR\"}");
    }
  }

  @PostMapping("/db/chart")
  public ResponseEntity<String> dbChart(@RequestBody(required = false) String body) {
    String corrId = UUID.randomUUID().toString();
    String base = resolveAgentBase();
    String target = base + "/v1/agent/db/chart";

    Map<String, Object> auditPayload = new HashMap<>();
    auditPayload.put("agent_base", base);
    AuditLogger.log("agent.db_chart.request", corrId, auditPayload);

    HttpHeaders headers = new HttpHeaders();
    headers.setContentType(MediaType.APPLICATION_JSON);
    RequestEntity<String> req =
        RequestEntity.post(URI.create(target))
            .headers(headers)
            .body(body != null && !body.isBlank() ? body : "{}");
    try {
      ResponseEntity<String> resp = restTemplate.exchange(req, String.class);
      Map<String, Object> respAudit = new HashMap<>();
      respAudit.put("status", resp.getStatusCode().value());
      AuditLogger.log("agent.db_chart.response", corrId, respAudit);
      return ResponseEntity.status(resp.getStatusCode()).body(resp.getBody());
    } catch (RestClientException ex) {
      Map<String, Object> respAudit = new HashMap<>();
      respAudit.put("status", 502);
      respAudit.put("error", ex.getMessage());
      AuditLogger.log("agent.db_chart.error", corrId, respAudit);
      return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
          .body("{\"code\":\"BACKEND_ERROR\"}");
    }
  }

  @PostMapping("/excel/chart")
  public ResponseEntity<String> excelChart(@RequestBody(required = false) String body) {
    String corrId = UUID.randomUUID().toString();
    String base = resolveAgentBase();
    String target = base + "/v1/agent/excel/chart";

    Map<String, Object> auditPayload = new HashMap<>();
    auditPayload.put("agent_base", base);
    AuditLogger.log("agent.excel_chart.request", corrId, auditPayload);

    HttpHeaders headers = new HttpHeaders();
    headers.setContentType(MediaType.APPLICATION_JSON);
    RequestEntity<String> req =
        RequestEntity.post(URI.create(target))
            .headers(headers)
            .body(body != null && !body.isBlank() ? body : "{}");
    try {
      ResponseEntity<String> resp = restTemplate.exchange(req, String.class);
      Map<String, Object> respAudit = new HashMap<>();
      respAudit.put("status", resp.getStatusCode().value());
      AuditLogger.log("agent.excel_chart.response", corrId, respAudit);
      return ResponseEntity.status(resp.getStatusCode()).body(resp.getBody());
    } catch (RestClientException ex) {
      Map<String, Object> respAudit = new HashMap<>();
      respAudit.put("status", 502);
      respAudit.put("error", ex.getMessage());
      AuditLogger.log("agent.excel_chart.error", corrId, respAudit);
      return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
          .body("{\"code\":\"BACKEND_ERROR\"}");
    }
  }

  @PostMapping("/threads/{threadId}/invoke")
  public ResponseEntity<String> invokeThread(
      @PathVariable("threadId") String threadId,
      @RequestBody(required = false) String body) {
    String corrId = UUID.randomUUID().toString();
    String base = resolveAgentBase();
    String target = base + "/v1/agent/threads/" + threadId + "/invoke";
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
            sys.put("content", AGENT_SYSTEM_PROMPT);
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
