package com.cv.cp.service;

import java.util.List;
import java.util.Map;

public interface ModelAliasService {

  List<Map<String, Object>> listAliases();

  void putAlias(String alias, String modelId, String version);

  void deleteAlias(String alias);

  void promote(String alias, String modelId, String version);

  void rollback(String alias);

  List<Map<String, Object>> listHistory(String alias);
}

