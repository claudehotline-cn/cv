package com.cv.cp.controller;

import com.cv.cp.config.AppProperties;
import java.sql.Connection;
import java.sql.SQLException;
import java.util.HashMap;
import java.util.Map;
import javax.sql.DataSource;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/_debug")
public class DebugController {

  private final AppProperties appProperties;
  private final DataSource dataSource;

  public DebugController(AppProperties appProperties, DataSource dataSource) {
    this.appProperties = appProperties;
    this.dataSource = dataSource;
  }

  @GetMapping("/echo")
  public ResponseEntity<CpResponse<Map<String, Object>>> echo(
      @RequestParam("path") String path) {
    Map<String, Object> data = new HashMap<>();
    data.put("path", path);
    return ResponseEntity.ok(new CpResponse<>("OK", null, data));
  }

  @GetMapping("/sub/get")
  public ResponseEntity<CpResponse<Map<String, Object>>> subGet(
      @RequestParam("id") String id) {
    Map<String, Object> data = new HashMap<>();
    data.put("id", id);
    // Spring 版暂不维护内存订阅存储，这里仅返回 found=false 占位行为。
    data.put("found", false);
    return ResponseEntity.ok(new CpResponse<>("OK", null, data));
  }

  @GetMapping("/db")
  public ResponseEntity<CpResponse<Map<String, Object>>> dbInfo() {
    Map<String, Object> cfg = new HashMap<>();
    AppProperties.DbProperties db = appProperties.getDb();
    if (db != null) {
      cfg.put("driver", db.getDriver());
      cfg.put("host", db.getHost());
      cfg.put("port", db.getPort());
      cfg.put("user", db.getUser());
      cfg.put("schema", db.getSchema());
    }
    Map<String, Object> errors = new HashMap<>();
    boolean connected = false;
    try (Connection conn = dataSource.getConnection()) {
      if (conn != null && !conn.isClosed()) {
        connected = true;
      }
    } catch (SQLException ex) {
      errors.put("last_error", ex.getMessage());
    }
    cfg.put("connected", connected);
    Map<String, Object> data = new HashMap<>();
    data.put("errors", errors);
    data.put("cfg", cfg);
    CpResponse<Map<String, Object>> body = new CpResponse<>("OK", null, data);
    return ResponseEntity.ok(body);
  }
}

