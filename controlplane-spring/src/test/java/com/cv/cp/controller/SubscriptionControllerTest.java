package com.cv.cp.controller;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.cv.cp.config.AppProperties;
import com.cv.cp.domain.subscription.SubscriptionRecord;
import com.cv.cp.service.SubscriptionService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(SubscriptionController.class)
@Import({ObjectMapper.class})
class SubscriptionControllerTest {

  @Autowired
  private MockMvc mockMvc;

  @MockBean
  private SubscriptionService subscriptionService;

  @MockBean
  private AppProperties appProperties;

  @Test
  void createSubscriptionShouldReturnAccepted() throws Exception {
    when(subscriptionService.create(any()))
        .thenReturn(new SubscriptionRecord("s1:det_720p", "\"etag-1\"", "s1", "det_720p",
            "rtsp://127.0.0.1:8554/camera_01", null));
    String body = "{\"stream_id\":\"s1\",\"profile\":\"det_720p\",\"source_id\":\"camera_01\"}";
    mockMvc.perform(post("/api/subscriptions")
            .contentType("application/json")
            .content(body))
        .andExpect(status().isAccepted());
    verify(subscriptionService).create(any());
  }
}

