package com.cv.cp.controller;

import com.cv.cp.logging.AuditLogger;
import com.cv.cp.service.ControlService;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/control")
public class ControlController {

  private final ObjectMapper objectMapper;
  private final ControlService controlService;

  public ControlController(ObjectMapper objectMapper, ControlService controlService) {
    this.objectMapper = objectMapper;
    this.controlService = controlService;
  }

  @PostMapping("/apply_pipeline")
  public ResponseEntity<CpResponse<Void>> applyPipeline(@RequestBody(required = false) String body) {
    String corrId = java.util.UUID.randomUUID().toString();
    if (body == null || body.isBlank()) {
      AuditLogger.log(
          "control.apply_pipeline.reject",
          corrId,
          java.util.Map.of("reason", "empty body"));
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
    JsonNode node;
    try {
      node = objectMapper.readTree(body);
    } catch (JsonProcessingException ex) {
      AuditLogger.log(
          "control.apply_pipeline.reject",
          corrId,
          java.util.Map.of("reason", "invalid json"));
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
    String pipelineName = null;
    String yamlPath = null;
    String graphId = null;
    String serialized = null;
    if (node.has("pipeline_name") && node.get("pipeline_name").isTextual()) {
      pipelineName = node.get("pipeline_name").asText();
    }
    if (node.has("spec") && node.get("spec").isObject()) {
      JsonNode spec = node.get("spec");
      if (spec.has("yaml_path") && spec.get("yaml_path").isTextual()) {
        yamlPath = spec.get("yaml_path").asText();
      }
      if (spec.has("graph_id") && spec.get("graph_id").isTextual()) {
        graphId = spec.get("graph_id").asText();
      }
      if (spec.has("serialized") && spec.get("serialized").isTextual()) {
        serialized = spec.get("serialized").asText();
      }
    } else {
      if (node.has("yaml_path") && node.get("yaml_path").isTextual()) {
        yamlPath = node.get("yaml_path").asText();
      }
      if (node.has("graph_id") && node.get("graph_id").isTextual()) {
        graphId = node.get("graph_id").asText();
      }
      if (node.has("serialized") && node.get("serialized").isTextual()) {
        serialized = node.get("serialized").asText();
      }
    }
    if (pipelineName == null || (yamlPath == null && graphId == null && serialized == null)) {
      AuditLogger.log(
          "control.apply_pipeline.reject",
          corrId,
          java.util.Map.of("reason", "missing pipeline/spec"));
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument(null));
    }
    AuditLogger.log(
        "control.apply_pipeline.request",
        corrId,
        java.util.Map.of(
            "pipeline_name", pipelineName,
            "has_yaml", yamlPath != null,
            "has_graph", graphId != null,
            "has_serialized", serialized != null));
    controlService.applyPipeline(pipelineName, yamlPath, graphId, serialized);
    AuditLogger.log(
        "control.apply_pipeline.response",
        corrId,
        java.util.Map.of("pipeline_name", pipelineName, "status", 202));
    return ResponseEntity.status(HttpStatus.ACCEPTED).body(CpResponse.accepted(null));
  }

  @PostMapping("/drain")
  public ResponseEntity<CpResponse<Void>> drain(@RequestBody(required = false) String body) {
    String corrId = java.util.UUID.randomUUID().toString();
    if (body == null || body.isBlank()) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
    JsonNode node;
    try {
      node = objectMapper.readTree(body);
    } catch (JsonProcessingException ex) {
      AuditLogger.log(
          "control.drain.reject",
          corrId,
          java.util.Map.of("reason", "invalid json"));
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
    JsonNode nameNode = node.get("pipeline_name");
    if (nameNode == null || !nameNode.isTextual() || nameNode.asText().isEmpty()) {
      AuditLogger.log(
          "control.drain.reject",
          corrId,
          java.util.Map.of("reason", "missing pipeline_name"));
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument(null));
    }
    int timeoutSec = 60;
    JsonNode timeoutNode = node.get("timeout_sec");
    if (timeoutNode != null && timeoutNode.canConvertToInt()) {
      timeoutSec = timeoutNode.asInt();
    }
    AuditLogger.log(
        "control.drain.request",
        corrId,
        java.util.Map.of("pipeline_name", nameNode.asText(), "timeout_sec", timeoutSec));
    controlService.drain(nameNode.asText(), timeoutSec);
    AuditLogger.log(
        "control.drain.response",
        corrId,
        java.util.Map.of("pipeline_name", nameNode.asText(), "status", 202));
    return ResponseEntity.status(HttpStatus.ACCEPTED).body(CpResponse.accepted(null));
  }

  @PostMapping("/remove_pipeline")
  public ResponseEntity<CpResponse<Void>> removePipeline(
      @RequestBody(required = false) String body) {
    String corrId = java.util.UUID.randomUUID().toString();
    if (body == null || body.isBlank()) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
    JsonNode node;
    try {
      node = objectMapper.readTree(body);
    } catch (JsonProcessingException ex) {
      AuditLogger.log(
          "control.remove_pipeline.reject",
          corrId,
          java.util.Map.of("reason", "invalid json"));
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
    JsonNode nameNode = node.get("pipeline_name");
    if (nameNode == null || !nameNode.isTextual() || nameNode.asText().isEmpty()) {
      AuditLogger.log(
          "control.remove_pipeline.reject",
          corrId,
          java.util.Map.of("reason", "missing pipeline_name"));
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument(null));
    }
    controlService.removePipeline(nameNode.asText());
    AuditLogger.log(
        "control.remove_pipeline.response",
        corrId,
        java.util.Map.of("pipeline_name", nameNode.asText(), "status", 200));
    return ResponseEntity.ok(CpResponse.ok(null));
  }

  @PostMapping("/hotswap")
  public ResponseEntity<CpResponse<Void>> hotSwap(@RequestBody(required = false) String body) {
    String corrId = java.util.UUID.randomUUID().toString();
    if (body == null || body.isBlank()) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
    JsonNode node;
    try {
      node = objectMapper.readTree(body);
    } catch (JsonProcessingException ex) {
      AuditLogger.log(
          "control.hotswap.reject",
          corrId,
          java.util.Map.of("reason", "invalid json"));
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
    JsonNode pipelineNode = node.get("pipeline_name");
    JsonNode modelNode = node.get("model_uri");
    JsonNode hNode = node.get("node");
    if (pipelineNode == null || !pipelineNode.isTextual()
        || modelNode == null || !modelNode.isTextual()
        || hNode == null || !hNode.isTextual()) {
      AuditLogger.log(
          "control.hotswap.reject",
          corrId,
          java.util.Map.of("reason", "missing fields"));
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument(null));
    }
    controlService.hotSwapModel(pipelineNode.asText(), hNode.asText(), modelNode.asText());
    AuditLogger.log(
        "control.hotswap.response",
        corrId,
        java.util.Map.of(
            "pipeline_name", pipelineNode.asText(),
            "node", hNode.asText(),
            "status", 200));
    return ResponseEntity.ok(CpResponse.ok(null));
  }

  @PostMapping("/set_engine")
  public ResponseEntity<CpResponse<Void>> setEngine(@RequestBody(required = false) String body) {
    String corrId = java.util.UUID.randomUUID().toString();
    if (body == null || body.isBlank()) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
    JsonNode node;
    try {
      node = objectMapper.readTree(body);
    } catch (JsonProcessingException ex) {
      AuditLogger.log(
          "control.set_engine.reject",
          corrId,
          java.util.Map.of("reason", "invalid json"));
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
    Map<String, Object> options = new HashMap<>();
    if (node.has("type") && node.get("type").isTextual()) {
      options.put("type", node.get("type").asText());
    }
    if (node.has("provider") && node.get("provider").isTextual()) {
      options.put("provider", node.get("provider").asText());
    }
    if (node.has("device") && node.get("device").canConvertToInt()) {
      options.put("device", node.get("device").asInt());
    }
    if (node.has("options") && node.get("options").isObject()) {
      Map<String, Object> optMap = new HashMap<>();
      node.get("options")
          .fields()
          .forEachRemaining(e -> optMap.put(e.getKey(), e.getValue().asText()));
      options.put("options", optMap);
    }
    if (options.isEmpty()) {
      AuditLogger.log(
          "control.set_engine.reject",
          corrId,
          java.util.Map.of("reason", "empty options"));
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument(null));
    }
    controlService.setEngine(options);
    AuditLogger.log(
        "control.set_engine.response",
        corrId,
        java.util.Map.of("status", 200));
    return ResponseEntity.ok(CpResponse.ok(null));
  }

  @GetMapping("/pipelines")
  public ResponseEntity<CpResponse<List<Map<String, Object>>>> listPipelines() {
    List<Map<String, Object>> data = controlService.listPipelines();
    String corrId = java.util.UUID.randomUUID().toString();
    AuditLogger.log(
        "control.list_pipelines.response",
        corrId,
        java.util.Map.of("count", data != null ? data.size() : 0));
    return ResponseEntity.ok(CpResponse.ok(data));
  }
}
