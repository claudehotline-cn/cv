package com.cv.cp.service.impl;

import com.cv.cp.domain.source.SourceItem;
import com.cv.cp.grpc.VideoSourceManagerClient;
import com.cv.cp.service.SourceService;
import io.grpc.StatusRuntimeException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

@Service
public class SourceServiceImpl implements SourceService {

  private static final Logger log = LoggerFactory.getLogger(SourceServiceImpl.class);

  private final Map<String, SourceItem> sources = new ConcurrentHashMap<>();
  private final VideoSourceManagerClient vsmClient;

  public SourceServiceImpl(VideoSourceManagerClient vsmClient) {
    this.vsmClient = vsmClient;
  }

  @Override
  public void attach(String attachId, String sourceUri, String pipelineId) {
    try {
      vsmClient.attach(attachId, sourceUri, pipelineId);
    } catch (StatusRuntimeException ex) {
      log.warn("VSM Attach failed for {}: {}", attachId, ex.toString());
    }
    SourceItem item = new SourceItem();
    item.setAttachId(attachId);
    item.setSourceUri(sourceUri);
    item.setPipelineId(pipelineId);
    item.setEnabled(true);
    sources.put(attachId, item);
  }

  @Override
  public void detach(String attachId) {
    try {
      vsmClient.detach(attachId);
    } catch (StatusRuntimeException ex) {
      log.warn("VSM Detach failed for {}: {}", attachId, ex.toString());
    }
    sources.remove(attachId);
  }

  @Override
  public void setEnabled(String attachId, boolean enabled) {
    try {
      vsmClient.setEnabled(attachId, enabled);
    } catch (StatusRuntimeException ex) {
      log.warn("VSM setEnabled failed for {} -> {}: {}", attachId, enabled, ex.toString());
    }
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
