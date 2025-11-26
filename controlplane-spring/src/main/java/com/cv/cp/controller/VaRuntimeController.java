package com.cv.cp.controller;

import com.cv.cp.grpc.VideoAnalyzerClient;
import java.util.HashMap;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import va.v1.QueryRuntimeReply;

@RestController
@RequestMapping("/api/va")
public class VaRuntimeController {

  private final VideoAnalyzerClient videoAnalyzerClient;

  public VaRuntimeController(VideoAnalyzerClient videoAnalyzerClient) {
    this.videoAnalyzerClient = videoAnalyzerClient;
  }

  @GetMapping("/runtime")
  public ResponseEntity<CpResponse<Map<String, Object>>> getRuntime() {
    QueryRuntimeReply reply = videoAnalyzerClient.queryRuntime();
    Map<String, Object> data = new HashMap<>();
    data.put("provider", reply.getProvider());
    data.put("gpu_active", reply.getGpuActive());
    data.put("io_binding", reply.getIoBinding());
    data.put("device_binding", reply.getDeviceBinding());
    return ResponseEntity.ok(CpResponse.ok(data));
  }
}

