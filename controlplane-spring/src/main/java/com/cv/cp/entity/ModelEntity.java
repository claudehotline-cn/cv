package com.cv.cp.entity;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;
import lombok.Getter;
import lombok.Setter;

@TableName("models")
@Getter
@Setter
public class ModelEntity {

  @TableId
  private String id;
  private String task;
  private String family;
  private String variant;
  private String path;
  private Double conf;
  private Double iou;
  private LocalDateTime createdAt;
  private LocalDateTime updatedAt;
}
