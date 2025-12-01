package com.cv.cp.config;

import java.util.List;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class CorsConfig implements WebMvcConfigurer {

  private final AppProperties appProperties;

  public CorsConfig(AppProperties appProperties) {
    this.appProperties = appProperties;
  }

  @Override
  public void addCorsMappings(CorsRegistry registry) {
    AppProperties.SecurityProperties security = appProperties.getSecurity();
    if (security == null || security.getCors() == null) {
      return;
    }
    AppProperties.CorsProperties cors = security.getCors();
    List<String> origins = cors.getAllowedOrigins();
    if (origins == null || origins.isEmpty()) {
      return;
    }

    registry
        .addMapping("/**")
        .allowedOrigins(origins.toArray(new String[0]))
        .allowedMethods("GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD")
        .allowedHeaders("*");
  }
}

