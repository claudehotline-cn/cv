package com.cv.cp.entity;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;
import lombok.Getter;
import lombok.Setter;

@TableName("graphs")
@Getter
@Setter
public class GraphEntity {

  @TableId
  private String id;
  private String name;
  private String requires;
  private String filePath;
  private LocalDateTime createdAt;
  private LocalDateTime updatedAt;
}
