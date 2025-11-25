package com.cv.cp.dto;

import lombok.Data;

@Data
public class SubscriptionStatusDto {

  private String id;
  private String phase;
  private String pipelineKey;
}
