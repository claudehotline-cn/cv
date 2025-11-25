package com.cv.cp.dto;

import lombok.Data;

@Data
public class SubscriptionCreateDto {

  private String streamId;
  private String profile;
  private String sourceUri;
  private String modelId;
}
