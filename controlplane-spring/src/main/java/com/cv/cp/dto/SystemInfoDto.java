package com.cv.cp.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

@Data
public class SystemInfoDto {

  private RestreamInfo restream;

  @Data
  public static class RestreamInfo {

    @JsonProperty("rtsp_base")
    private String rtspBase;
  }
}
