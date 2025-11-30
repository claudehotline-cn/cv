package com.cv.cp.service;

import java.util.List;
import java.util.Map;

public interface GrayRolloutService {

  Map<String, Object> start(Map<String, Object> payload);

  Map<String, Object> status(String id);

  List<String> consumeEvents(String id, int fromIndex);
}

