package com.cv.cp.controller;

import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.cv.cp.service.CacheService;
import com.cv.cp.service.SourceService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(SourceController.class)
@Import({ObjectMapper.class})
class SourceControllerTest {

  @Autowired
  private MockMvc mockMvc;

  @MockBean
  private SourceService sourceService;

  @MockBean
  private CacheService cacheService;

  @Test
  void attachShouldValidateParamsAndCallService() throws Exception {
    mockMvc.perform(post("/api/sources:attach")
            .param("attach_id", "test-1")
            .param("source_uri", "rtsp://127.0.0.1:8554/camera_01"))
        .andExpect(status().isAccepted());
    verify(sourceService).attach("test-1", "rtsp://127.0.0.1:8554/camera_01", null);
  }
}

