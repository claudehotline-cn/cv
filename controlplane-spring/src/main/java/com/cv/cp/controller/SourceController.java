package com.cv.cp.controller;

import com.cv.cp.dto.SourcesListDto;
import com.cv.cp.logging.AuditLogger;
import com.cv.cp.service.CacheService;
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
@RequestMapping("/api")
public class SourceController {

  private final SourceService sourceService;
  private final ObjectMapper objectMapper;
  private final CacheService cacheService;

  public SourceController(
      SourceService sourceService, ObjectMapper objectMapper, CacheService cacheService) {
    this.sourceService = sourceService;
    this.objectMapper = objectMapper;
    this.cacheService = cacheService;
  }

  @PostMapping("/sources:attach")
  public ResponseEntity<CpResponse<Void>> attach(
      @RequestParam("attach_id") String attachId,
      @RequestParam("source_uri") String sourceUri,
      @RequestParam(value = "pipeline_id", required = false) String pipelineId) {
    String corrId = java.util.UUID.randomUUID().toString();
    if (attachId == null || attachId.isEmpty() || sourceUri == null || sourceUri.isEmpty()) {
      AuditLogger.log(
          "sources.attach.reject",
          corrId,
          java.util.Map.of("reason", "missing attach_id/source_uri"));
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument(null));
    }
    AuditLogger.log(
        "sources.attach.request",
        corrId,
        java.util.Map.of("attach_id", attachId, "source_uri", sourceUri));
    sourceService.attach(attachId, sourceUri, pipelineId);
    cacheService.evictSources();
    AuditLogger.log(
        "sources.attach.response",
        corrId,
        java.util.Map.of("attach_id", attachId, "status", 202));
    return ResponseEntity.status(HttpStatus.ACCEPTED).body(CpResponse.accepted(null));
  }

  @PostMapping("/sources:detach")
  public ResponseEntity<CpResponse<Void>> detach(
      @RequestParam("attach_id") String attachId) {
    if (attachId == null || attachId.isEmpty()) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument(null));
    }
    sourceService.detach(attachId);
    cacheService.evictSources();
    return ResponseEntity.status(HttpStatus.ACCEPTED).body(CpResponse.accepted(null));
  }

  @PostMapping("/sources:enable")
  public ResponseEntity<CpResponse<Void>> enable(@RequestBody(required = false) String body) {
    String attachId = parseAttachId(body);
    if (attachId == null) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument(null));
    }
    sourceService.setEnabled(attachId, true);
    cacheService.evictSources();
    return ResponseEntity.status(HttpStatus.ACCEPTED).body(CpResponse.accepted(null));
  }

  @PostMapping("/sources:disable")
  public ResponseEntity<CpResponse<Void>> disable(@RequestBody(required = false) String body) {
    String attachId = parseAttachId(body);
    if (attachId == null) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument(null));
    }
    sourceService.setEnabled(attachId, false);
    cacheService.evictSources();
    return ResponseEntity.status(HttpStatus.ACCEPTED).body(CpResponse.accepted(null));
  }

  @GetMapping("/sources")
  public ResponseEntity<CpResponse<SourcesListDto>> listSources() {
    SourcesListDto listDto = cacheService.getSources();
    return ResponseEntity.ok(CpResponse.ok(listDto));
  }

  private String parseAttachId(String body) {
    if (body == null || body.isBlank()) {
      return null;
    }
    JsonNode node;
    try {
      node = objectMapper.readTree(body);
    } catch (JsonProcessingException ex) {
      return null;
    }
    JsonNode value = node.get("attach_id");
    if (value == null || !value.isTextual()) {
      return null;
    }
    String attachId = value.asText();
    if (attachId.isEmpty()) {
      return null;
    }
    return attachId;
  }
}
