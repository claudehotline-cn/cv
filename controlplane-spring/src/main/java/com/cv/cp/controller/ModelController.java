package com.cv.cp.controller;

import com.cv.cp.service.ModelReadService;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
public class ModelController {

  private final ModelReadService modelReadService;

  public ModelController(ModelReadService modelReadService) {
    this.modelReadService = modelReadService;
  }

  @GetMapping("/models")
  public ResponseEntity<CpResponse<List<Map<String, Object>>>> listModels() {
    List<Map<String, Object>> data;
    try {
      data = modelReadService.listModels();
    } catch (Exception ex) {
      data = Collections.emptyList();
    }
    return ResponseEntity.ok(CpResponse.ok(data));
  }
}

