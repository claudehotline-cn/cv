package com.cv.cp.domain.source;

import lombok.Data;

@Data
public class SourceItem {

  private String attachId;
  private String sourceUri;
  private String pipelineId;
  private boolean enabled;
}
