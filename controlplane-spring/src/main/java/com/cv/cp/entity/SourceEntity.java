package com.cv.cp.entity;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;
import lombok.Getter;
import lombok.Setter;

@TableName("sources")
@Getter
@Setter
public class SourceEntity {

  @TableId
  private String id;
  private String uri;
  private String status;
  private String caps;
  private Double fps;
  private LocalDateTime createdAt;
  private LocalDateTime updatedAt;
}
