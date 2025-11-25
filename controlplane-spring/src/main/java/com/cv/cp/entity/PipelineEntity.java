package com.cv.cp.entity;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;
import lombok.Getter;
import lombok.Setter;

@TableName("pipelines")
@Getter
@Setter
public class PipelineEntity {

  @TableId
  private String name;
  private String graphId;
  private String defaultModelId;
  private String encoderCfg;
  private LocalDateTime createdAt;
  private LocalDateTime updatedAt;
}
