package com.cv.cp.service;

import com.cv.cp.domain.source.SourceItem;
import java.util.List;

public interface SourceService {

  void attach(String attachId, String sourceUri, String pipelineId);

  void detach(String attachId);

  void setEnabled(String attachId, boolean enabled);

  List<SourceItem> list();
}

