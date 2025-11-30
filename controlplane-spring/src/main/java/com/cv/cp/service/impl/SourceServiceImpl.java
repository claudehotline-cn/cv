package com.cv.cp.service.impl;

import com.cv.cp.domain.source.SourceItem;
import com.cv.cp.grpc.VideoSourceManagerClient;
import com.cv.cp.service.SourceService;
import java.util.ArrayList;
import java.util.List;
import org.springframework.stereotype.Service;

@Service
public class SourceServiceImpl implements SourceService {

  private final VideoSourceManagerClient vsmClient;

  public SourceServiceImpl(VideoSourceManagerClient vsmClient) {
    this.vsmClient = vsmClient;
  }

  @Override
  public void attach(String attachId, String sourceUri, String pipelineId) {
    vsmClient.attach(attachId, sourceUri, pipelineId);
  }

  @Override
  public void detach(String attachId) {
    vsmClient.detach(attachId);
  }

  @Override
  public void setEnabled(String attachId, boolean enabled) {
    vsmClient.setEnabled(attachId, enabled);
  }

  @Override
  public List<SourceItem> list() {
    var health = vsmClient.getHealth();
    List<SourceItem> out = new ArrayList<>();
    health.getStreamsList()
        .forEach(
            s -> {
              SourceItem item = new SourceItem();
              item.setAttachId(s.getAttachId());
              // 当前 GetHealth.StreamStat proto 未暴露 source_uri 字段，这里仅维护 attachId 与 enabled，
              // 具体 sourceUri 由上层缓存层在无数据时合成默认 camera_01。
              item.setSourceUri(null);
              item.setEnabled("Ready".equalsIgnoreCase(s.getPhase()));
              out.add(item);
            });
    return out;
  }
}
