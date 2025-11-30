package com.cv.cp.controller;

import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.cv.cp.config.AppProperties;
import com.cv.cp.service.ControlService;
import com.cv.cp.service.SourceService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(OrchestratorController.class)
@Import({ObjectMapper.class})
class OrchestratorControllerTest {

  @Autowired
  private MockMvc mockMvc;

  @MockBean
  private SourceService sourceService;

  @MockBean
  private ControlService controlService;

  @MockBean
  private AppProperties appProperties;

  @Test
  void attachApplyShouldUseSourceIdWhenNoSourceUri() throws Exception {
    AppProperties.RestreamProperties restream = new AppProperties.RestreamProperties();
    restream.setRtspBase("rtsp://127.0.0.1:8554/");
    when(appProperties.getRestream()).thenReturn(restream);

    String body = """
        {
          "attach_id": "orch-1",
          "source_id": "camera_01"
        }
        """;

    mockMvc.perform(post("/api/orch/attach_apply")
            .contentType("application/json")
            .content(body))
        .andExpect(status().isAccepted());

    verify(sourceService).attach("orch-1", "rtsp://127.0.0.1:8554/camera_01", null);
  }
}

