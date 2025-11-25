package com.cv.cp.controller;

import com.cv.cp.service.PipelineReadService;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
public class PipelineController {

  private final PipelineReadService pipelineReadService;

  public PipelineController(PipelineReadService pipelineReadService) {
    this.pipelineReadService = pipelineReadService;
  }

  @GetMapping("/pipelines")
  public ResponseEntity<CpResponse<List<Map<String, Object>>>> listPipelines() {
    List<Map<String, Object>> data;
    try {
      data = pipelineReadService.listPipelines();
    } catch (Exception ex) {
      data = Collections.emptyList();
    }
    return ResponseEntity.ok(CpResponse.ok(data));
  }
}

