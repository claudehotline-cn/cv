package com.cv.cp.controller;

import com.cv.cp.service.ModelAliasService;
import com.cv.cp.service.impl.ModelAliasServiceImpl;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/models/aliases")
public class ModelAliasController {

  private final ModelAliasService aliasService;
  private final ObjectMapper objectMapper;

  public ModelAliasController(ModelAliasService aliasService, ObjectMapper objectMapper) {
    this.aliasService = aliasService;
    this.objectMapper = objectMapper;
  }

  @GetMapping
  public ResponseEntity<CpResponse<List<Map<String, Object>>>> list() {
    List<Map<String, Object>> data = aliasService.listAliases();
    return ResponseEntity.ok(CpResponse.ok(data));
  }

  @PostMapping
  public ResponseEntity<CpResponse<Void>> upsert(@RequestBody(required = false) String body) {
    if (body == null || body.isBlank()) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
    try {
      JsonNode node = objectMapper.readTree(body);
      String alias = text(node, "alias");
      String modelId = text(node, "model_id");
      String version = text(node, "version");
      if (alias == null || alias.isEmpty() || modelId == null || modelId.isEmpty()) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
            .body(CpResponse.invalidArgument(null));
      }
      aliasService.putAlias(alias, modelId, version);
      return ResponseEntity.ok(CpResponse.ok(null));
    } catch (Exception ex) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
  }

  @DeleteMapping("/{alias}")
  public ResponseEntity<CpResponse<Void>> delete(@PathVariable("alias") String alias) {
    aliasService.deleteAlias(alias);
    return ResponseEntity.ok(CpResponse.ok(null));
  }

  @PostMapping("/promote")
  public ResponseEntity<CpResponse<Void>> promote(@RequestBody(required = false) String body) {
    if (body == null || body.isBlank()) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
    try {
      JsonNode node = objectMapper.readTree(body);
      String alias = text(node, "alias");
      String modelId = text(node, "model_id");
      String version = text(node, "version");
      if (alias == null || alias.isEmpty() || modelId == null || modelId.isEmpty()) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
            .body(CpResponse.invalidArgument(null));
      }
      aliasService.promote(alias, modelId, version);
      return ResponseEntity.ok(CpResponse.ok(null));
    } catch (Exception ex) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
  }

  @PostMapping("/rollback")
  public ResponseEntity<CpResponse<Void>> rollback(@RequestBody(required = false) String body) {
    if (body == null || body.isBlank()) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
    try {
      JsonNode node = objectMapper.readTree(body);
      String alias = text(node, "alias");
      if (alias == null || alias.isEmpty()) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
            .body(CpResponse.invalidArgument(null));
      }
      try {
        aliasService.rollback(alias);
        return ResponseEntity.ok(CpResponse.ok(null));
      } catch (ModelAliasServiceImpl.NotFoundException ex) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
            .body(new CpResponse<>("NOT_FOUND", "no previous mapping", null));
      }
    } catch (Exception ex) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
  }

  @GetMapping("/history")
  public ResponseEntity<CpResponse<List<Map<String, Object>>>> history(
      @RequestParam(value = "alias", required = false) String alias) {
    List<Map<String, Object>> data = aliasService.listHistory(alias);
    return ResponseEntity.ok(CpResponse.ok(data));
  }

  private String text(JsonNode node, String field) {
    JsonNode v = node.get(field);
    if (v == null || !v.isTextual()) {
      return null;
    }
    return v.asText();
  }
}

