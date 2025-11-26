package com.cv.cp.grpc;

import com.cv.cp.config.AppProperties;
import com.google.protobuf.ByteString;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import io.grpc.ManagedChannel;
import io.grpc.StatusRuntimeException;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Component;
import va.v1.AnalyzerControlGrpc;
import va.v1.AnalyzerControlGrpc.AnalyzerControlBlockingStub;
import va.v1.ApplyPipelineReply;
import va.v1.ApplyPipelineRequest;
import va.v1.DrainReply;
import va.v1.DrainRequest;
import va.v1.HotSwapModelReply;
import va.v1.HotSwapModelRequest;
import va.v1.ListPipelinesReply;
import va.v1.ListPipelinesRequest;
import va.v1.PipelineItem;
import va.v1.PipelineSpec;
import va.v1.QueryRuntimeReply;
import va.v1.QueryRuntimeRequest;
import va.v1.RemovePipelineReply;
import va.v1.RemovePipelineRequest;
import va.v1.SetEngineReply;
import va.v1.SetEngineRequest;
import va.v1.SubscribePipelineReply;
import va.v1.SubscribePipelineRequest;
import va.v1.UnsubscribePipelineReply;
import va.v1.UnsubscribePipelineRequest;

@Component
public class VideoAnalyzerClient {

  private final ManagedChannel channel;
  private final AppProperties properties;

  public VideoAnalyzerClient(
      @Qualifier("vaChannel") ManagedChannel channel, AppProperties properties) {
    this.channel = channel;
    this.properties = properties;
  }

  private AnalyzerControlBlockingStub blockingStub() {
    int timeoutMs =
        properties.getVa() != null && properties.getVa().getTimeoutMs() > 0
            ? properties.getVa().getTimeoutMs()
            : 30_000;
    return AnalyzerControlGrpc.newBlockingStub(channel)
        .withDeadlineAfter(timeoutMs, TimeUnit.MILLISECONDS);
  }

  @CircuitBreaker(name = "va")
  public String subscribePipeline(String streamId, String profile, String sourceUri,
      String modelId)
      throws StatusRuntimeException {
    SubscribePipelineRequest.Builder builder =
        SubscribePipelineRequest.newBuilder()
            .setStreamId(streamId)
            .setProfile(profile)
            .setSourceUri(sourceUri);
    if (modelId != null) {
      builder.setModelId(modelId);
    }
    SubscribePipelineReply reply = blockingStub().subscribePipeline(builder.build());
    return reply.getSubscriptionId();
  }

  @CircuitBreaker(name = "va")
  public void unsubscribePipeline(String streamId, String profile) throws StatusRuntimeException {
    UnsubscribePipelineRequest request =
        UnsubscribePipelineRequest.newBuilder().setStreamId(streamId).setProfile(profile).build();
    UnsubscribePipelineReply unused = blockingStub().unsubscribePipeline(request);
  }

  @CircuitBreaker(name = "va")
  public void applyPipeline(String pipelineName, String yamlPath, String graphId, String serialized)
      throws StatusRuntimeException {
    PipelineSpec.Builder spec = PipelineSpec.newBuilder();
    if (yamlPath != null) {
      spec.setYamlPath(yamlPath);
    }
    if (graphId != null) {
      spec.setGraphId(graphId);
    }
    if (serialized != null) {
      spec.setSerialized(ByteString.copyFromUtf8(serialized));
      spec.setFormat("json");
    }
    ApplyPipelineRequest request =
        ApplyPipelineRequest.newBuilder().setPipelineName(pipelineName).setSpec(spec).build();
    ApplyPipelineReply unused = blockingStub().applyPipeline(request);
  }

  @CircuitBreaker(name = "va")
  public void drainPipeline(String pipelineName, int timeoutSec) throws StatusRuntimeException {
    DrainRequest request =
        DrainRequest.newBuilder().setPipelineName(pipelineName).setTimeoutSec(timeoutSec).build();
    DrainReply unused = blockingStub().drain(request);
  }

  @CircuitBreaker(name = "va")
  public ListPipelinesReply listPipelines() throws StatusRuntimeException {
    ListPipelinesRequest request = ListPipelinesRequest.newBuilder().build();
    return blockingStub().listPipelines(request);
  }

  @CircuitBreaker(name = "va")
  public QueryRuntimeReply queryRuntime() throws StatusRuntimeException {
    QueryRuntimeRequest request = QueryRuntimeRequest.newBuilder().build();
    return blockingStub().queryRuntime(request);
  }

  @CircuitBreaker(name = "va")
  public void removePipeline(String pipelineName) throws StatusRuntimeException {
    RemovePipelineRequest request =
        RemovePipelineRequest.newBuilder().setPipelineName(pipelineName).build();
    RemovePipelineReply unused = blockingStub().removePipeline(request);
  }

  @CircuitBreaker(name = "va")
  public void hotSwapModel(String pipelineName, String node, String modelUri)
      throws StatusRuntimeException {
    HotSwapModelRequest request =
        HotSwapModelRequest.newBuilder()
            .setPipelineName(pipelineName)
            .setNode(node)
            .setModelUri(modelUri)
            .build();
    HotSwapModelReply unused = blockingStub().hotSwapModel(request);
  }

  @CircuitBreaker(name = "va")
  public void setEngine(Map<String, Object> options) throws StatusRuntimeException {
    SetEngineRequest.Builder builder = SetEngineRequest.newBuilder();
    Object provider = options.get("provider");
    if (provider instanceof String p && !p.isEmpty()) {
      builder.setProvider(p);
    }
    Object type = options.get("type");
    if (type instanceof String t && !t.isEmpty()) {
      builder.setType(t);
    }
    Object device = options.get("device");
    if (device instanceof Number n) {
      builder.setDevice(n.intValue());
    }
    Object opts = options.get("options");
    if (opts instanceof Map<?, ?> m) {
      for (Map.Entry<?, ?> e : m.entrySet()) {
        Object k = e.getKey();
        Object v = e.getValue();
        if (k != null && v != null) {
          builder.putOptions(k.toString(), v.toString());
        }
      }
    }
    SetEngineRequest request = builder.build();
    SetEngineReply unused = blockingStub().setEngine(request);
  }

  @CircuitBreaker(name = "va")
  public java.util.List<PipelineItem> listPipelineItems() throws StatusRuntimeException {
    return listPipelines().getItemsList();
  }
}
