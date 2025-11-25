package com.cv.cp.controller;

import com.cv.cp.config.AppProperties;
import com.cv.cp.domain.subscription.SubscriptionRecord;
import com.cv.cp.dto.SubscriptionCreateDto;
import com.cv.cp.dto.SubscriptionStatusDto;
import com.cv.cp.service.SubscriptionService;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.URI;
import java.util.Optional;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/subscriptions")
public class SubscriptionController {

  private final SubscriptionService subscriptionService;
  private final ObjectMapper objectMapper;
  private final AppProperties appProperties;

  public SubscriptionController(
      SubscriptionService subscriptionService, ObjectMapper objectMapper,
      AppProperties appProperties) {
    this.subscriptionService = subscriptionService;
    this.objectMapper = objectMapper;
    this.appProperties = appProperties;
  }

  @PostMapping
  public ResponseEntity<CpResponse<?>> createSubscription(
      @RequestParam(value = "stream_id", required = false) String streamIdParam,
      @RequestParam(value = "profile", required = false) String profileParam,
      @RequestParam(value = "source_uri", required = false) String sourceUriParam,
      @RequestParam(value = "model_id", required = false) String modelIdParam,
      @RequestBody(required = false) String body) {
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
    SubscriptionCreateDto request = new SubscriptionCreateDto();
    String sourceId = null;
    if (node.has("stream_id") && node.get("stream_id").isTextual()) {
      request.setStreamId(node.get("stream_id").asText());
    }
    if (node.has("profile") && node.get("profile").isTextual()) {
      request.setProfile(node.get("profile").asText());
    }
    if (node.has("source_uri") && node.get("source_uri").isTextual()) {
      request.setSourceUri(node.get("source_uri").asText());
    }
    if (node.has("source_id") && node.get("source_id").isTextual()) {
      sourceId = node.get("source_id").asText();
    }
    if (node.has("model_id") && node.get("model_id").isTextual()) {
      request.setModelId(node.get("model_id").asText());
    }
    if (request.getStreamId() == null) {
      request.setStreamId(streamIdParam);
    }
    if (request.getProfile() == null) {
      request.setProfile(profileParam);
    }
    if (request.getSourceUri() == null) {
      request.setSourceUri(sourceUriParam);
    }
    if (request.getSourceUri() == null && sourceId != null) {
      String base = null;
      if (appProperties.getRestream() != null) {
        base = appProperties.getRestream().getRtspBase();
      }
      if (base != null && !base.isEmpty()) {
        if (!base.endsWith("/")) {
          base = base + "/";
        }
        request.setSourceUri(base + sourceId);
      }
    }
    if (request.getModelId() == null) {
      request.setModelId(modelIdParam);
    }
    if (request.getStreamId() == null
        || request.getProfile() == null
        || request.getSourceUri() == null) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument(null));
    }
    SubscriptionRecord record = subscriptionService.create(request);
    SubscriptionStatusDto statusDto = new SubscriptionStatusDto();
    statusDto.setId(record.getId());
    statusDto.setPhase("pending");
    statusDto.setPipelineKey(record.getId());
    CpResponse<SubscriptionStatusDto> response = CpResponse.accepted(statusDto);
    HttpHeaders headers = new HttpHeaders();
    headers.setLocation(URI.create("/api/subscriptions/" + record.getId()));
    headers.setETag(record.getEtag());
    headers.add("Access-Control-Expose-Headers", "Location, ETag, Accept-Patch");
    return new ResponseEntity<>(response, headers, HttpStatus.ACCEPTED);
  }

  @GetMapping("/{id}")
  public ResponseEntity<CpResponse<?>> getSubscription(
      @PathVariable("id") String id,
      @RequestHeader(value = "If-None-Match", required = false) String ifNoneMatch) {
    Optional<SubscriptionRecord> optional = subscriptionService.find(id);
    if (optional.isEmpty()) {
      return ResponseEntity.status(HttpStatus.NOT_FOUND)
          .body(new CpResponse<>("NOT_FOUND", null, null));
    }
    SubscriptionRecord record = optional.get();
    String etag = record.getEtag();
    HttpHeaders headers = new HttpHeaders();
    if (etag != null) {
      headers.setETag(etag);
      headers.add("Access-Control-Expose-Headers", "ETag,Location");
    }
    if (etag != null && etag.equals(ifNoneMatch)) {
      return new ResponseEntity<>(null, headers, HttpStatus.NOT_MODIFIED);
    }
    SubscriptionStatusDto statusDto = new SubscriptionStatusDto();
    statusDto.setId(record.getId());
    statusDto.setPhase("pending");
    statusDto.setPipelineKey(record.getId());
    CpResponse<SubscriptionStatusDto> response = CpResponse.ok(statusDto);
    return new ResponseEntity<>(response, headers, HttpStatus.OK);
  }

  @DeleteMapping("/{id}")
  public ResponseEntity<CpResponse<Void>> deleteSubscription(@PathVariable("id") String id) {
    subscriptionService.delete(id);
    CpResponse<Void> response = CpResponse.accepted(null);
    return ResponseEntity.status(HttpStatus.ACCEPTED).body(response);
  }
}
