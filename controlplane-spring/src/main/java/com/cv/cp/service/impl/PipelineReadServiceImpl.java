package com.cv.cp.service.impl;

import com.cv.cp.entity.PipelineEntity;
import com.cv.cp.mapper.PipelineMapper;
import com.cv.cp.service.PipelineReadService;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;

@Service
public class PipelineReadServiceImpl implements PipelineReadService {

  private final PipelineMapper pipelineMapper;
  private final ObjectMapper objectMapper;

  public PipelineReadServiceImpl(PipelineMapper pipelineMapper, ObjectMapper objectMapper) {
    this.pipelineMapper = pipelineMapper;
    this.objectMapper = objectMapper;
  }

  @Override
  public List<Map<String, Object>> listPipelines() {
    List<PipelineEntity> entities = pipelineMapper.selectList(null);
    List<Map<String, Object>> result = new ArrayList<>();
    for (PipelineEntity e : entities) {
      Map<String, Object> m = new HashMap<>();
      m.put("name", e.getName());
      if (e.getGraphId() != null) {
        m.put("graph_id", e.getGraphId());
      }
      if (e.getDefaultModelId() != null) {
        m.put("default_model_id", e.getDefaultModelId());
      }
      if (e.getEncoderCfg() != null) {
        try {
          JsonNode node = objectMapper.readTree(e.getEncoderCfg());
          m.put("encoder_cfg", node);
        } catch (Exception ignore) {
          // ignore invalid encoder_cfg JSON to keep compatibility
        }
      }
      result.add(m);
    }
    return result;
  }
}

