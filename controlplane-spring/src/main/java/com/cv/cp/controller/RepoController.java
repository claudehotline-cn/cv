package com.cv.cp.controller;

import com.cv.cp.grpc.VideoAnalyzerClient;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.grpc.StatusRuntimeException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import va.v1.RepoModel;

@RestController
@RequestMapping("/api/repo")
public class RepoController {

  private final VideoAnalyzerClient videoAnalyzerClient;
  private final ObjectMapper objectMapper;

  public RepoController(VideoAnalyzerClient videoAnalyzerClient, ObjectMapper objectMapper) {
    this.videoAnalyzerClient = videoAnalyzerClient;
    this.objectMapper = objectMapper;
  }

  @PostMapping(path = "/load", consumes = MediaType.APPLICATION_JSON_VALUE)
  public ResponseEntity<CpResponse<Void>> load(@RequestBody(required = false) String body) {
    String model = parseModel(body);
    if (model == null) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
    if (model.isEmpty()) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument(null));
    }
    videoAnalyzerClient.repoLoad(model);
    return ResponseEntity.ok(CpResponse.ok(null));
  }

  @PostMapping(path = "/unload", consumes = MediaType.APPLICATION_JSON_VALUE)
  public ResponseEntity<CpResponse<Void>> unload(@RequestBody(required = false) String body) {
    String model = parseModel(body);
    if (model == null) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
    if (model.isEmpty()) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument(null));
    }
    videoAnalyzerClient.repoUnload(model);
    return ResponseEntity.ok(CpResponse.ok(null));
  }

  @PostMapping(path = "/poll", consumes = MediaType.APPLICATION_JSON_VALUE)
  public ResponseEntity<CpResponse<Void>> poll(
      @RequestBody(required = false) String body) {
    // body 可为空，保持与 C++ 行为一致
    videoAnalyzerClient.repoPoll();
    return ResponseEntity.ok(CpResponse.ok(null));
  }

  @PostMapping(path = "/remove", consumes = MediaType.APPLICATION_JSON_VALUE)
  public ResponseEntity<CpResponse<Void>> remove(@RequestBody(required = false) String body) {
    String model = parseModel(body);
    if (model == null) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
    if (model.isEmpty()) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument(null));
    }
    videoAnalyzerClient.repoRemoveModel(model);
    return ResponseEntity.ok(CpResponse.ok(null));
  }

  @PostMapping(
      path = "/upload",
      consumes = MediaType.APPLICATION_OCTET_STREAM_VALUE)
  public ResponseEntity<String> upload(
      @RequestParam("model") String model,
      @RequestParam(value = "version", required = false) String version,
      @RequestParam("filename") String filename,
      @RequestBody(required = false) byte[] body) {
    if (model == null || model.isEmpty() || filename == null || filename.isEmpty()) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(
              "{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"model/filename required\"}");
    }
    if (body == null || body.length == 0) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(
              "{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"file content required\"}");
    }
    String ver = (version == null || version.isEmpty()) ? "1" : version;
    videoAnalyzerClient.repoPutFile(model, ver, filename, body);
    String json =
        "{\"code\":\"CREATED\",\"data\":{\"model\":\""
            + escape(model)
            + "\",\"version\":\""
            + escape(ver)
            + "\",\"filename\":\""
            + escape(filename)
            + "\"}}";
    return ResponseEntity.status(HttpStatus.CREATED).body(json);
  }

  @PostMapping(path = "/add", consumes = MediaType.APPLICATION_JSON_VALUE)
  public ResponseEntity<CpResponse<Map<String, Object>>> add(
      @RequestBody(required = false) String body) {
    if (body == null || body.isBlank()) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
    try {
      JsonNode node = objectMapper.readTree(body);
      String model = text(node, "model");
      String content = text(node, "config");
      boolean autoload = false;
      if (node.has("load") && node.get("load").isBoolean()) {
        autoload = node.get("load").asBoolean();
      }
      if (model == null || model.isEmpty()) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
            .body(CpResponse.invalidArgument(null));
      }
      if (content == null || content.isEmpty()) {
        content = "name: \"" + model + "\"\n";
      }
      videoAnalyzerClient.repoSaveConfig(model, content);
      if (autoload) {
        try {
          videoAnalyzerClient.repoLoad(model);
        } catch (StatusRuntimeException ignored) {
          // best-effort
        }
      }
      Map<String, Object> data = new HashMap<>();
      data.put("id", model);
      data.put("loaded", autoload);
      return ResponseEntity.status(HttpStatus.CREATED)
          .body(new CpResponse<>("CREATED", null, data));
    } catch (JsonProcessingException ex) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
  }

  @GetMapping("/list")
  public ResponseEntity<CpResponse<List<Map<String, Object>>>> list() {
    List<RepoModel> models = videoAnalyzerClient.repoList();
    List<Map<String, Object>> data = new ArrayList<>();
    for (RepoModel m : models) {
      Map<String, Object> row = new HashMap<>();
      row.put("id", m.getId());
      if (!m.getPath().isEmpty()) {
        row.put("path", m.getPath());
      }
      row.put("ready", m.getReady());
      if (m.getVersionsCount() > 0) {
        row.put("versions", new ArrayList<>(m.getVersionsList()));
      }
      if (!m.getActiveVersion().isEmpty()) {
        row.put("active_version", m.getActiveVersion());
      }
      data.add(row);
    }
    return ResponseEntity.ok(CpResponse.ok(data));
  }

  @GetMapping(path = "/config")
  public ResponseEntity<CpResponse<Map<String, Object>>> getConfig(
      @RequestParam("model") String model) {
    if (model == null || model.isEmpty()) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument(null));
    }
    String content = videoAnalyzerClient.repoGetConfig(model);
    Map<String, Object> data = new HashMap<>();
    data.put("model", model);
    data.put("content", content);
    return ResponseEntity.ok(CpResponse.ok(data));
  }

  @PostMapping(path = "/config", consumes = MediaType.APPLICATION_JSON_VALUE)
  public ResponseEntity<CpResponse<Void>> saveConfig(
      @RequestBody(required = false) String body) {
    if (body == null || body.isBlank()) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
    try {
      JsonNode node = objectMapper.readTree(body);
      String model = text(node, "model");
      String content = text(node, "content");
      if (model == null || model.isEmpty()) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
            .body(CpResponse.invalidArgument(null));
      }
      if (content == null) {
        content = "";
      }
      videoAnalyzerClient.repoSaveConfig(model, content);
      return ResponseEntity.ok(CpResponse.ok(null));
    } catch (JsonProcessingException ex) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(CpResponse.invalidArgument("INVALID_JSON"));
    }
  }

  @PostMapping(path = "/convert_upload", consumes = MediaType.APPLICATION_OCTET_STREAM_VALUE)
  public ResponseEntity<String> convertUpload(
      @RequestParam("model") String model,
      @RequestParam(value = "version", required = false) String version,
      @RequestParam(value = "filename", required = false) String filename,
      @RequestBody(required = false) byte[] body) {
    if (model == null || model.isEmpty()) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(
              "{\"code\":\"INVALID_ARGUMENT\","
                  + "\"msg\":\"model required\"}");
    }
    if (body == null || body.length == 0) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(
              "{\"code\":\"INVALID_ARGUMENT\","
                  + "\"msg\":\"ONNX bytes required in request body (Content-Type: application/octet-stream)\"}");
    }
    String ver = (version == null || version.isEmpty()) ? "1" : version;
    try {
      String jobId = videoAnalyzerClient.repoConvertUpload(model, ver, body);
      String events = "/api/repo/convert/events?job=" + jobId;
      String json =
          "{\"code\":\"ACCEPTED\",\"data\":{\"job\":\""
              + escape(jobId)
              + "\",\"events\":\""
              + events
              + "\"}}";
      return ResponseEntity.status(HttpStatus.ACCEPTED).body(json);
    } catch (StatusRuntimeException ex) {
      String code = ex.getStatus().getCode().name();
      String msg = ex.getStatus().getDescription();
      if (msg == null || msg.isEmpty()) {
        msg = "convert_upload failed";
      }
      String json =
          "{\"code\":\""
              + escape(code)
              + "\",\"msg\":\""
              + escape(msg)
              + "\"}";
      return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(json);
    }
  }

  @PostMapping(path = "/convert/cancel", consumes = MediaType.APPLICATION_JSON_VALUE)
  public ResponseEntity<String> convertCancel(@RequestBody(required = false) String body) {
    String job = null;
    if (body != null && !body.isBlank()) {
      try {
        JsonNode node = objectMapper.readTree(body);
        if (node.has("job") && node.get("job").isTextual()) {
          job = node.get("job").asText();
        }
      } catch (Exception ex) {
        // fall through to INVALID_JSON
      }
    }
    if (job == null || job.isEmpty()) {
      return ResponseEntity.status(HttpStatus.BAD_REQUEST)
          .body(
              "{\"code\":\"INVALID_ARGUMENT\","
                  + "\"msg\":\"job required\"}");
    }
    try {
      videoAnalyzerClient.repoConvertCancel(job);
      return ResponseEntity.ok("{\"code\":\"OK\"}");
    } catch (StatusRuntimeException ex) {
      String code = ex.getStatus().getCode().name();
      String msg = ex.getStatus().getDescription();
      if (msg == null || msg.isEmpty()) {
        msg = "cancel failed";
      }
      String json =
          "{\"code\":\""
              + escape(code)
              + "\",\"msg\":\""
              + escape(msg)
              + "\"}";
      return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(json);
    }
  }

  private String parseModel(String body) {
    if (body == null || body.isBlank()) {
      return null;
    }
    try {
      JsonNode node = objectMapper.readTree(body);
      if (node.has("model") && node.get("model").isTextual()) {
        return node.get("model").asText();
      }
      return "";
    } catch (JsonProcessingException ex) {
      return null;
    }
  }

  private String text(JsonNode node, String field) {
    JsonNode v = node.get(field);
    if (v == null || !v.isTextual()) {
      return null;
    }
    return v.asText();
  }

  private String escape(String s) {
    return s.replace("\\", "\\\\").replace("\"", "\\\"");
  }
}
