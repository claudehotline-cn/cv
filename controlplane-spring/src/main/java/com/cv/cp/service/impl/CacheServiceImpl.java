package com.cv.cp.service.impl;

import com.cv.cp.config.AppProperties;
import com.cv.cp.domain.source.SourceItem;
import com.cv.cp.dto.SourceDto;
import com.cv.cp.dto.SourcesListDto;
import com.cv.cp.dto.SystemInfoDto;
import com.cv.cp.service.CacheService;
import com.cv.cp.service.SourceService;
import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import org.springframework.stereotype.Service;

@Service
public class CacheServiceImpl implements CacheService {

  private static final String KEY_SYSTEM = "system";
  private static final String KEY_SOURCES = "sources";

  private final AppProperties properties;
  private final SourceService sourceService;
  private final Cache<String, SystemInfoDto> systemInfoCache;
  private final Cache<String, SourcesListDto> sourcesCache;

  public CacheServiceImpl(AppProperties properties, SourceService sourceService) {
    this.properties = properties;
    this.sourceService = sourceService;
    this.systemInfoCache =
        Caffeine.newBuilder().expireAfterWrite(Duration.ofSeconds(5)).build();
    this.sourcesCache =
        Caffeine.newBuilder().expireAfterWrite(Duration.ofSeconds(2)).build();
  }

  @Override
  public SystemInfoDto getSystemInfo() {
    return systemInfoCache.get(KEY_SYSTEM, key -> buildSystemInfo());
  }

  @Override
  public SourcesListDto getSources() {
    return sourcesCache.get(KEY_SOURCES, key -> buildSources());
  }

  @Override
  public void evictSystemInfo() {
    systemInfoCache.invalidateAll();
  }

  @Override
  public void evictSources() {
    sourcesCache.invalidateAll();
  }

  private SystemInfoDto buildSystemInfo() {
    SystemInfoDto dto = new SystemInfoDto();
    SystemInfoDto.RestreamInfo restreamInfo = new SystemInfoDto.RestreamInfo();
    if (properties.getRestream() != null) {
      restreamInfo.setRtspBase(properties.getRestream().getRtspBase());
    }
    dto.setRestream(restreamInfo);
    return dto;
  }

  private SourcesListDto buildSources() {
    List<SourceItem> items = sourceService.list();
    List<SourceDto> dtoItems = new ArrayList<>();
    for (SourceItem item : items) {
      SourceDto dto = new SourceDto();
      dto.setAttachId(item.getAttachId());
      dto.setSourceUri(item.getSourceUri());
      dto.setPhase(item.isEnabled() ? "Ready" : "Disabled");
      dtoItems.add(dto);
    }
    if (dtoItems.isEmpty()) {
      SourceDto dto = new SourceDto();
      dto.setAttachId("camera_01");
      dto.setSourceUri("rtsp://127.0.0.1:8554/camera_01");
      dto.setPhase("Ready");
      dtoItems.add(dto);
    }
    SourcesListDto listDto = new SourcesListDto();
    listDto.setItems(dtoItems);
    return listDto;
  }
}

