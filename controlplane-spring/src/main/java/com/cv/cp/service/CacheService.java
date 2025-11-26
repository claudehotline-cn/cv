package com.cv.cp.service;

import com.cv.cp.dto.SourcesListDto;
import com.cv.cp.dto.SystemInfoDto;

public interface CacheService {

  SystemInfoDto getSystemInfo();

  SourcesListDto getSources();

  void evictSystemInfo();

  void evictSources();
}

