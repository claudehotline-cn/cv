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
              item.setSourceUri(s.getAttachId().isEmpty() ? null : s.getAttachId());
              item.setEnabled("Ready".equalsIgnoreCase(s.getPhase()));
              out.add(item);
            });
    return out;
  }
}
