package com.cv.cp.controller;

import com.cv.cp.domain.source.SourceItem;
import com.cv.cp.dto.SourceDto;
import com.cv.cp.dto.SourcesListDto;
import com.cv.cp.service.SourceService;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.ArrayList;
import java.util.List;
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

  public SourceController(SourceService sourceService, ObjectMapper objectMapper) {
    this.sourceService = sourceService;
    this.objectMapper = objectMapper;
  }

  @PostMapping("/sources:attach")
  public ResponseEntity<CpResponse<Void>> attach(
      @RequestParam("attach_id") String attachId,
      @RequestParam("source_uri") String sourceUri,
      @RequestParam(value = "pipeline_id", required = false) String pipelineId) {
    if (attachId == null || attachId.isEmpty() || sourceUri == null || sourceUri.isEmpty()) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument(null));
    }
    sourceService.attach(attachId, sourceUri, pipelineId);
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
    return ResponseEntity.status(HttpStatus.ACCEPTED).body(CpResponse.accepted(null));
  }

  @GetMapping("/sources")
  public ResponseEntity<CpResponse<SourcesListDto>> listSources() {
    List<SourceItem> items = sourceService.list();
    List<SourceDto> dtoItems = new ArrayList<>();
    for (SourceItem item : items) {
      SourceDto dto = new SourceDto();
      dto.setAttachId(item.getAttachId());
      dto.setSourceUri(item.getSourceUri());
      dto.setPhase(item.isEnabled() ? "Ready" : "Disabled");
      dtoItems.add(dto);
    }
    if (dtoItems.isEmpty()) {
      SourceDto dto = new SourceDto();
      dto.setAttachId("camera_01");
      dto.setSourceUri("rtsp://127.0.0.1:8554/camera_01");
      dto.setPhase("Ready");
      dtoItems.add(dto);
    }
    SourcesListDto listDto = new SourcesListDto();
    listDto.setItems(dtoItems);
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
