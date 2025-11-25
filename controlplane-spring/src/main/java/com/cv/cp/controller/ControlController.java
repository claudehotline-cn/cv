package com.cv.cp.controller;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/control")
public class ControlController {

  private final ObjectMapper objectMapper;

  public ControlController(ObjectMapper objectMapper) {
    this.objectMapper = objectMapper;
  }

  @PostMapping("/apply_pipeline")
  public ResponseEntity<CpResponse<Void>> applyPipeline(@RequestBody(required = false) String body) {
    if (body == null || body.isBlank()) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
    JsonNode node;
    try {
      node = objectMapper.readTree(body);
    } catch (JsonProcessingException ex) {
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
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument(null));
    }
    return ResponseEntity.status(HttpStatus.ACCEPTED).body(CpResponse.accepted(null));
  }

  @PostMapping("/drain")
  public ResponseEntity<CpResponse<Void>> drain(@RequestBody(required = false) String body) {
    if (body == null || body.isBlank()) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
    JsonNode node;
    try {
      node = objectMapper.readTree(body);
    } catch (JsonProcessingException ex) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
    JsonNode nameNode = node.get("pipeline_name");
    if (nameNode == null || !nameNode.isTextual() || nameNode.asText().isEmpty()) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument(null));
    }
    return ResponseEntity.status(HttpStatus.ACCEPTED).body(CpResponse.accepted(null));
  }
}

