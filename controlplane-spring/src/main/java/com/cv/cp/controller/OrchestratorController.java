package com.cv.cp.controller;

import com.cv.cp.service.ControlService;
import com.cv.cp.service.SourceService;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/orch")
public class OrchestratorController {

  private final SourceService sourceService;
  private final ControlService controlService;
  private final ObjectMapper objectMapper;

  public OrchestratorController(
      SourceService sourceService, ControlService controlService, ObjectMapper objectMapper) {
    this.sourceService = sourceService;
    this.controlService = controlService;
    this.objectMapper = objectMapper;
  }

  @PostMapping("/attach_apply")
  public ResponseEntity<CpResponse<Void>> attachApply(
      @RequestBody(required = false) String body,
      @RequestParam(value = "attach_id", required = false) String attachIdParam,
      @RequestParam(value = "source_uri", required = false) String sourceUriParam,
      @RequestParam(value = "source_id", required = false) String sourceIdParam,
      @RequestParam(value = "pipeline_name", required = false) String pipelineNameParam) {
    String attachId = attachIdParam;
    String sourceUri = sourceUriParam;
    String sourceId = sourceIdParam;
    String pipelineName = pipelineNameParam;
    String yamlPath = null;
    String graphId = null;
    String serialized = null;

    if (body != null && !body.isBlank()) {
      JsonNode root;
      try {
        root = objectMapper.readTree(body);
      } catch (JsonProcessingException ex) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
            .body(CpResponse.invalidArgument("INVALID_JSON"));
      }
      if (attachId == null && root.has("attach_id") && root.get("attach_id").isTextual()) {
        attachId = root.get("attach_id").asText();
      }
      if (sourceUri == null && root.has("source_uri") && root.get("source_uri").isTextual()) {
        sourceUri = root.get("source_uri").asText();
      }
      if (sourceId == null && root.has("source_id") && root.get("source_id").isTextual()) {
        sourceId = root.get("source_id").asText();
      }
      if (pipelineName == null && root.has("pipeline_name")
          && root.get("pipeline_name").isTextual()) {
        pipelineName = root.get("pipeline_name").asText();
      }
      if (root.has("spec") && root.get("spec").isObject()) {
        JsonNode spec = root.get("spec");
        if (spec.has("yaml_path") && spec.get("yaml_path").isTextual()) {
          yamlPath = spec.get("yaml_path").asText();
        }
        if (spec.has("graph_id") && spec.get("graph_id").isTextual()) {
          graphId = spec.get("graph_id").asText();
        }
        if (spec.has("serialized") && spec.get("serialized").isTextual()) {
          serialized = spec.get("serialized").asText();
        }
      }
    }

    if (sourceUri == null && sourceId != null && !sourceId.isEmpty()) {
      // 兼容 C++ 行为：允许通过 source_id 组装 RTSP URI，具体前缀由前端或 restream 配置控制；
      // 这里不强制拼接，保持最小实现，要求调用方传入 source_uri。
    }
    if (attachId == null || attachId.isEmpty() || sourceUri == null || sourceUri.isEmpty()) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument(null));
    }

    // 1) 调用 VSM Attach（通过 SourceService 封装）
    sourceService.attach(attachId, sourceUri, pipelineName);

    // 2) 如提供管线信息，则在 VA 上应用管线
    if (pipelineName != null || yamlPath != null || graphId != null || serialized != null) {
      String effectiveName = pipelineName != null ? pipelineName : attachId;
      controlService.applyPipeline(effectiveName, yamlPath, graphId, serialized);
    }

    return ResponseEntity.status(HttpStatus.ACCEPTED)
        .body(CpResponse.accepted(null));
  }

  @PostMapping("/detach_remove")
  public ResponseEntity<CpResponse<Void>> detachRemove(
      @RequestBody(required = false) String body,
      @RequestParam(value = "attach_id", required = false) String attachIdParam,
      @RequestParam(value = "pipeline_name", required = false) String pipelineNameParam) {
    String attachId = attachIdParam;
    String pipelineName = pipelineNameParam;
    if (body != null && !body.isBlank()) {
      JsonNode root;
      try {
        root = objectMapper.readTree(body);
      } catch (JsonProcessingException ex) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
            .body(CpResponse.invalidArgument("INVALID_JSON"));
      }
      if (attachId == null && root.has("attach_id") && root.get("attach_id").isTextual()) {
        attachId = root.get("attach_id").asText();
      }
      if (pipelineName == null && root.has("pipeline_name")
          && root.get("pipeline_name").isTextual()) {
        pipelineName = root.get("pipeline_name").asText();
      }
    }
    if ((attachId == null || attachId.isEmpty())
        && (pipelineName == null || pipelineName.isEmpty())) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument(null));
    }
    // best effort：detach 源并移除管线，异常通过全局异常处理映射
    if (attachId != null && !attachId.isEmpty()) {
      sourceService.detach(attachId);
    }
    if (pipelineName != null && !pipelineName.isEmpty()) {
      controlService.removePipeline(pipelineName);
    }
    return ResponseEntity.status(HttpStatus.ACCEPTED).body(CpResponse.accepted(null));
  }

  @GetMapping("/health")
  public ResponseEntity<CpResponse<Void>> health() {
    return ResponseEntity.ok(CpResponse.ok(null));
  }
}
