package com.cv.cp.controller;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.cv.cp.config.AppProperties;
import com.cv.cp.service.CacheService;
import com.cv.cp.service.impl.CacheServiceImpl;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(SystemInfoController.class)
@Import({ObjectMapper.class})
class SystemInfoControllerTest {

  @Autowired
  private MockMvc mockMvc;

  @MockBean
  private CacheService cacheService;

  @MockBean
  private AppProperties appProperties;

  @Test
  void systemInfoShouldContainRestreamField() throws Exception {
    mockMvc.perform(get("/api/system/info"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.code").value("OK"))
        .andExpect(jsonPath("$.data.restream").exists());
  }
}

