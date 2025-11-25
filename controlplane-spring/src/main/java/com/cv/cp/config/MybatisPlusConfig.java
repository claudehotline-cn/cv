package com.cv.cp.config;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.context.annotation.Configuration;

@Configuration
@MapperScan("com.cv.cp.mapper")
public class MybatisPlusConfig {
}
