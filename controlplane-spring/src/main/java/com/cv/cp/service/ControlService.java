package com.cv.cp.service;

import java.util.List;
import java.util.Map;

public interface ControlService {

  void applyPipeline(String pipelineName, String yamlPath, String graphId, String serialized);

  void drain(String pipelineName, int timeoutSec);

  void removePipeline(String pipelineName);

  void hotSwapModel(String pipelineName, String node, String modelUri);

  void setEngine(Map<String, Object> engineOptions);

  List<Map<String, Object>> listPipelines();
}

