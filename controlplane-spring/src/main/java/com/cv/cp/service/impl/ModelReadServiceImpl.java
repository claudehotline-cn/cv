package com.cv.cp.service.impl;

import com.cv.cp.entity.ModelEntity;
import com.cv.cp.mapper.ModelMapper;
import com.cv.cp.service.ModelReadService;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;

@Service
public class ModelReadServiceImpl implements ModelReadService {

  private final ModelMapper modelMapper;

  public ModelReadServiceImpl(ModelMapper modelMapper) {
    this.modelMapper = modelMapper;
  }

  @Override
  public List<Map<String, Object>> listModels() {
    List<ModelEntity> entities = modelMapper.selectList(null);
    List<Map<String, Object>> result = new ArrayList<>();
    for (ModelEntity e : entities) {
      Map<String, Object> m = new HashMap<>();
      m.put("id", e.getId());
      if (e.getTask() != null) {
        m.put("task", e.getTask());
      }
      if (e.getFamily() != null) {
        m.put("family", e.getFamily());
      }
      if (e.getVariant() != null) {
        m.put("variant", e.getVariant());
      }
      if (e.getPath() != null) {
        m.put("path", e.getPath());
      }
      result.add(m);
    }
    return result;
  }
}

