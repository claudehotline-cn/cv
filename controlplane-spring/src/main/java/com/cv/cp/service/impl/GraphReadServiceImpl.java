package com.cv.cp.service.impl;

import com.cv.cp.entity.GraphEntity;
import com.cv.cp.mapper.GraphMapper;
import com.cv.cp.service.GraphReadService;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;

@Service
public class GraphReadServiceImpl implements GraphReadService {

  private final GraphMapper graphMapper;

  public GraphReadServiceImpl(GraphMapper graphMapper) {
    this.graphMapper = graphMapper;
  }

  @Override
  public List<Map<String, Object>> listGraphs() {
    List<GraphEntity> entities = graphMapper.selectList(null);
    List<Map<String, Object>> result = new ArrayList<>();
    for (GraphEntity e : entities) {
      Map<String, Object> m = new HashMap<>();
      m.put("id", e.getId());
      if (e.getName() != null) {
        m.put("name", e.getName());
      }
      if (e.getRequires() != null) {
        m.put("requires", e.getRequires());
      }
      if (e.getFilePath() != null) {
        m.put("file_path", e.getFilePath());
      }
      result.add(m);
    }
    return result;
  }
}

