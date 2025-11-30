package com.cv.cp.controller;

import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.cv.cp.grpc.VideoAnalyzerClient;
import com.cv.cp.grpc.VideoSourceManagerClient;
import com.cv.cp.service.SubscriptionService;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.util.Collections;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.context.annotation.Configuration;
import org.springframework.test.web.servlet.MockMvc;
import vsm.v1.WatchStateReply;

@WebMvcTest(SseController.class)
@Import(SseControllerTest.TestConfig.class)
class SseControllerTest {

  @Autowired
  private MockMvc mockMvc;

  @MockBean
  private VideoSourceManagerClient vsmClient;

  @MockBean
  private VideoAnalyzerClient vaClient;

  @MockBean
  private SubscriptionService subscriptionService;

  @Configuration
  static class TestConfig {
    @Bean
    @Primary
    MeterRegistry meterRegistry() {
      return new SimpleMeterRegistry();
    }

    @Bean
    AtomicInteger sseConnections(MeterRegistry registry) {
      AtomicInteger g = new AtomicInteger(0);
      registry.gauge("cp.sse.connections.test", g);
      return g;
    }
  }

  @Test
  void demoIdEventsShouldReturn501() throws Exception {
    mockMvc.perform(get("/api/subscriptions/demo-id/events"))
        .andExpect(status().isNotImplemented());
  }

  @Test
  void sourcesWatchShouldReturn200() throws Exception {
    when(vsmClient.watchState(anyInt()))
        .thenReturn(Collections.<WatchStateReply>emptyList().iterator());
    mockMvc.perform(get("/api/sources/watch_sse"))
        .andExpect(status().isOk());
  }
}

