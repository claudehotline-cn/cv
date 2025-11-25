package com.cv.cp.grpc;

import com.cv.cp.config.AppProperties;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import io.grpc.ManagedChannel;
import io.grpc.StatusRuntimeException;
import java.util.concurrent.TimeUnit;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Component;
import va.v1.AnalyzerControlGrpc;
import va.v1.AnalyzerControlGrpc.AnalyzerControlBlockingStub;
import va.v1.ApplyPipelineReply;
import va.v1.ApplyPipelineRequest;
import va.v1.DrainReply;
import va.v1.DrainRequest;
import va.v1.ListPipelinesReply;
import va.v1.ListPipelinesRequest;
import va.v1.PipelineSpec;
import va.v1.QueryRuntimeReply;
import va.v1.QueryRuntimeRequest;
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
      spec.setSerialized(com.google.protobuf.ByteString.copyFromUtf8(serialized));
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
}
