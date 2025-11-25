package com.cv.cp.service.impl;

import com.cv.cp.domain.source.SourceItem;
import com.cv.cp.grpc.VideoSourceManagerClient;
import com.cv.cp.service.SourceService;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Service;

@Service
public class SourceServiceImpl implements SourceService {

  private final Map<String, SourceItem> sources = new ConcurrentHashMap<>();
  private final VideoSourceManagerClient vsmClient;

  public SourceServiceImpl(VideoSourceManagerClient vsmClient) {
    this.vsmClient = vsmClient;
  }

  @Override
  public void attach(String attachId, String sourceUri, String pipelineId) {
    vsmClient.attach(attachId, sourceUri, pipelineId);
    SourceItem item = new SourceItem();
    item.setAttachId(attachId);
    item.setSourceUri(sourceUri);
    item.setPipelineId(pipelineId);
    item.setEnabled(true);
    sources.put(attachId, item);
  }

  @Override
  public void detach(String attachId) {
    vsmClient.detach(attachId);
    sources.remove(attachId);
  }

  @Override
  public void setEnabled(String attachId, boolean enabled) {
    vsmClient.setEnabled(attachId, enabled);
    SourceItem item = sources.get(attachId);
    if (item == null) {
      item = new SourceItem();
      item.setAttachId(attachId);
      item.setEnabled(enabled);
      sources.put(attachId, item);
    } else {
      item.setEnabled(enabled);
    }
  }

  @Override
  public List<SourceItem> list() {
    return new ArrayList<>(sources.values());
  }
}
