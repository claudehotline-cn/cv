package com.cv.cp.entity;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;
import lombok.Getter;
import lombok.Setter;

@TableName("train_jobs")
@Getter
@Setter
public class TrainJobEntity {

  @TableId
  private String id;
  private String status;
  private String phase;
  private String cfg;
  private String mlflowRunId;
  private String registeredModel;
  private Integer registeredVersion;
  private String metrics;
  private String artifacts;
  private String error;
  private LocalDateTime createdAt;
  private LocalDateTime updatedAt;
}
