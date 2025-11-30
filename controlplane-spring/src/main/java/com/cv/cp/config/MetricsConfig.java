package com.cv.cp.config;

import io.micrometer.core.instrument.MeterRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class MetricsConfig {

  private static final Logger log = LoggerFactory.getLogger(MetricsConfig.class);

  @Bean
  public MeterRegistryCustomizer meterRegistryCustomizer() {
    return new MeterRegistryCustomizer();
  }

  public static class MeterRegistryCustomizer implements java.util.function.Consumer<MeterRegistry> {
    @Override
    public void accept(MeterRegistry registry) {
      try {
        registry.config().commonTags("app", "controlplane-spring");
      } catch (Exception ex) {
        log.warn("Failed to configure common tags for MeterRegistry", ex);
      }
    }
  }
}

