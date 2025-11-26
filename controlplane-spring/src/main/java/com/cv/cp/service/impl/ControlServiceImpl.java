package com.cv.cp.service.impl;

import com.cv.cp.grpc.VideoAnalyzerClient;
import com.cv.cp.service.ControlService;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;
import va.v1.PipelineItem;

@Service
public class ControlServiceImpl implements ControlService {

  private final VideoAnalyzerClient videoAnalyzerClient;

  public ControlServiceImpl(VideoAnalyzerClient videoAnalyzerClient) {
    this.videoAnalyzerClient = videoAnalyzerClient;
  }

  @Override
  public void applyPipeline(String pipelineName, String yamlPath, String graphId,
      String serialized) {
    videoAnalyzerClient.applyPipeline(pipelineName, yamlPath, graphId, serialized);
  }

  @Override
  public void drain(String pipelineName, int timeoutSec) {
    videoAnalyzerClient.drainPipeline(pipelineName, timeoutSec);
  }

  @Override
  public void removePipeline(String pipelineName) {
    videoAnalyzerClient.removePipeline(pipelineName);
  }

  @Override
  public void hotSwapModel(String pipelineName, String node, String modelUri) {
    videoAnalyzerClient.hotSwapModel(pipelineName, node, modelUri);
  }

  @Override
  public void setEngine(Map<String, Object> engineOptions) {
    videoAnalyzerClient.setEngine(engineOptions);
  }

  @Override
  public List<Map<String, Object>> listPipelines() {
    List<PipelineItem> items = videoAnalyzerClient.listPipelineItems();
    List<Map<String, Object>> result = new ArrayList<>();
    for (PipelineItem p : items) {
      Map<String, Object> m = new HashMap<>();
      m.put("key", p.getKey());
      m.put("stream_id", p.getStreamId());
      m.put("profile", p.getProfile());
      m.put("source_uri", p.getSourceUri());
      if (!p.getModelId().isEmpty()) {
        m.put("model_id", p.getModelId());
      }
      if (!p.getTask().isEmpty()) {
        m.put("task", p.getTask());
      }
      m.put("running", p.getRunning());
      m.put("fps", p.getFps());
      m.put("processed_frames", p.getProcessedFrames());
      m.put("dropped_frames", p.getDroppedFrames());
      m.put("transport_packets", p.getTransportPackets());
      m.put("transport_bytes", p.getTransportBytes());
      if (!p.getDecoderLabel().isEmpty()) {
        m.put("decoder_label", p.getDecoderLabel());
      }
      result.add(m);
    }
    return result;
  }
}

