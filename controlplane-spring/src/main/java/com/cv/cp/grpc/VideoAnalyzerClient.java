package com.cv.cp.grpc;

import com.cv.cp.config.AppProperties;
import com.google.protobuf.ByteString;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import io.grpc.ManagedChannel;
import io.grpc.Status;
import io.grpc.StatusRuntimeException;
import io.micrometer.core.instrument.MeterRegistry;
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
import va.v1.WatchRequest;
import va.v1.PhaseEvent;
import va.v1.RepoLoadRequest;
import va.v1.RepoLoadReply;
import va.v1.RepoUnloadRequest;
import va.v1.RepoUnloadReply;
import va.v1.RepoPollRequest;
import va.v1.RepoPollReply;
import va.v1.RepoListRequest;
import va.v1.RepoListReply;
import va.v1.RepoModel;
import va.v1.RepoGetConfigRequest;
import va.v1.RepoGetConfigReply;
import va.v1.RepoSaveConfigRequest;
import va.v1.RepoSaveConfigReply;
import va.v1.RepoPutFileRequest;
import va.v1.RepoPutFileReply;
import va.v1.RepoConvertUploadRequest;
import va.v1.RepoConvertUploadReply;
import va.v1.RepoConvertStreamRequest;
import va.v1.RepoConvertEvent;
import va.v1.RepoConvertCancelRequest;
import va.v1.RepoConvertCancelReply;
import va.v1.RepoRemoveModelRequest;
import va.v1.RepoRemoveModelReply;

@Component
public class VideoAnalyzerClient {

  private final ManagedChannel channel;
  private final AppProperties properties;
  private final MeterRegistry meterRegistry;

  public VideoAnalyzerClient(
      @Qualifier("vaChannel") ManagedChannel channel,
      AppProperties properties,
      MeterRegistry meterRegistry) {
    this.channel = channel;
    this.properties = properties;
    this.meterRegistry = meterRegistry;
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
    return meterRegistry
        .timer("cp.grpc.client", "svc", "va", "method", "SubscribePipeline")
        .record(
            () -> {
              SubscribePipelineReply reply = blockingStub().subscribePipeline(builder.build());
              return reply.getSubscriptionId();
            });
  }

  @CircuitBreaker(name = "va")
  public void unsubscribePipeline(String streamId, String profile) throws StatusRuntimeException {
    UnsubscribePipelineRequest request =
        UnsubscribePipelineRequest.newBuilder().setStreamId(streamId).setProfile(profile).build();
    meterRegistry
        .timer("cp.grpc.client", "svc", "va", "method", "UnsubscribePipeline")
        .record(
            () -> {
              UnsubscribePipelineReply unused = blockingStub().unsubscribePipeline(request);
            });
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
    meterRegistry
        .timer("cp.grpc.client", "svc", "va", "method", "ApplyPipeline")
        .record(
            () -> {
              ApplyPipelineReply unused = blockingStub().applyPipeline(request);
            });
  }

  @CircuitBreaker(name = "va")
  public void drainPipeline(String pipelineName, int timeoutSec) throws StatusRuntimeException {
    DrainRequest request =
        DrainRequest.newBuilder().setPipelineName(pipelineName).setTimeoutSec(timeoutSec).build();
    meterRegistry
        .timer("cp.grpc.client", "svc", "va", "method", "Drain")
        .record(
            () -> {
              DrainReply unused = blockingStub().drain(request);
            });
  }

  @CircuitBreaker(name = "va")
  public ListPipelinesReply listPipelines() throws StatusRuntimeException {
    ListPipelinesRequest request = ListPipelinesRequest.newBuilder().build();
    return meterRegistry
        .timer("cp.grpc.client", "svc", "va", "method", "ListPipelines")
        .record(
            () -> blockingStub().listPipelines(request));
  }

  @CircuitBreaker(name = "va")
  public QueryRuntimeReply queryRuntime() throws StatusRuntimeException {
    QueryRuntimeRequest request = QueryRuntimeRequest.newBuilder().build();
    return meterRegistry
        .timer("cp.grpc.client", "svc", "va", "method", "QueryRuntime")
        .record(
            () -> blockingStub().queryRuntime(request));
  }

  @CircuitBreaker(name = "va")
  public void removePipeline(String pipelineName) throws StatusRuntimeException {
    RemovePipelineRequest request =
        RemovePipelineRequest.newBuilder().setPipelineName(pipelineName).build();
    meterRegistry
        .timer("cp.grpc.client", "svc", "va", "method", "RemovePipeline")
        .record(
            () -> {
              RemovePipelineReply unused = blockingStub().removePipeline(request);
            });
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
    meterRegistry
        .timer("cp.grpc.client", "svc", "va", "method", "HotSwapModel")
        .record(
            () -> {
              HotSwapModelReply unused = blockingStub().hotSwapModel(request);
            });
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
    meterRegistry
        .timer("cp.grpc.client", "svc", "va", "method", "SetEngine")
        .record(
            () -> {
              SetEngineReply unused = blockingStub().setEngine(request);
            });
  }

  @CircuitBreaker(name = "va")
  public java.util.List<PipelineItem> listPipelineItems() throws StatusRuntimeException {
    return listPipelines().getItemsList();
  }

  @CircuitBreaker(name = "va")
  public java.util.Iterator<PhaseEvent> watch(String subscriptionId)
      throws StatusRuntimeException {
    WatchRequest request =
        WatchRequest.newBuilder().setSubscriptionId(subscriptionId).build();
    meterRegistry
        .counter("cp.grpc.client.stream.open", "svc", "va", "method", "Watch")
        .increment();
    return blockingStub().watch(request);
  }

  @CircuitBreaker(name = "va")
  public void repoLoad(String model) throws StatusRuntimeException {
    RepoLoadRequest request = RepoLoadRequest.newBuilder().setModel(model).build();
    meterRegistry
        .timer("cp.grpc.client", "svc", "va", "method", "RepoLoad")
        .record(
            () -> {
              RepoLoadReply reply = blockingStub().repoLoad(request);
              if (!reply.getOk()) {
                throw Status.INTERNAL.withDescription(reply.getMsg()).asRuntimeException();
              }
              return null;
            });
  }

  @CircuitBreaker(name = "va")
  public void repoUnload(String model) throws StatusRuntimeException {
    RepoUnloadRequest request = RepoUnloadRequest.newBuilder().setModel(model).build();
    meterRegistry
        .timer("cp.grpc.client", "svc", "va", "method", "RepoUnload")
        .record(
            () -> {
              RepoUnloadReply reply = blockingStub().repoUnload(request);
              if (!reply.getOk()) {
                throw Status.INTERNAL.withDescription(reply.getMsg()).asRuntimeException();
              }
              return null;
            });
  }

  @CircuitBreaker(name = "va")
  public void repoPoll() throws StatusRuntimeException {
    RepoPollRequest request = RepoPollRequest.newBuilder().build();
    meterRegistry
        .timer("cp.grpc.client", "svc", "va", "method", "RepoPoll")
        .record(
            () -> {
              RepoPollReply reply = blockingStub().repoPoll(request);
              if (!reply.getOk()) {
                throw Status.INTERNAL.withDescription(reply.getMsg()).asRuntimeException();
              }
              return null;
            });
  }

  @CircuitBreaker(name = "va")
  public java.util.List<RepoModel> repoList() throws StatusRuntimeException {
    RepoListRequest request = RepoListRequest.newBuilder().build();
    return meterRegistry
        .timer("cp.grpc.client", "svc", "va", "method", "RepoList")
        .record(
            () -> {
              RepoListReply reply = blockingStub().repoList(request);
              if (!reply.getOk()) {
                throw Status.INTERNAL.withDescription(reply.getMsg()).asRuntimeException();
              }
              return reply.getModelsList();
            });
  }

  @CircuitBreaker(name = "va")
  public String repoGetConfig(String model) throws StatusRuntimeException {
    RepoGetConfigRequest request =
        RepoGetConfigRequest.newBuilder().setModel(model).build();
    return meterRegistry
        .timer("cp.grpc.client", "svc", "va", "method", "RepoGetConfig")
        .record(
            () -> {
              RepoGetConfigReply reply = blockingStub().repoGetConfig(request);
              if (!reply.getOk()) {
                throw Status.INTERNAL.withDescription(reply.getMsg()).asRuntimeException();
              }
              return reply.getContent();
            });
  }

  @CircuitBreaker(name = "va")
  public void repoSaveConfig(String model, String content) throws StatusRuntimeException {
    RepoSaveConfigRequest request =
        RepoSaveConfigRequest.newBuilder()
            .setModel(model)
            .setContent(content)
            .build();
    meterRegistry
        .timer("cp.grpc.client", "svc", "va", "method", "RepoSaveConfig")
        .record(
            () -> {
              RepoSaveConfigReply reply = blockingStub().repoSaveConfig(request);
              if (!reply.getOk()) {
                throw Status.INTERNAL.withDescription(reply.getMsg()).asRuntimeException();
              }
              return null;
            });
  }

  @CircuitBreaker(name = "va")
  public void repoPutFile(String model, String version, String filename, byte[] content)
      throws StatusRuntimeException {
    RepoPutFileRequest request =
        RepoPutFileRequest.newBuilder()
            .setModel(model)
            .setVersion(version)
            .setFilename(filename)
            .setContent(ByteString.copyFrom(content))
            .build();
    meterRegistry
        .timer("cp.grpc.client", "svc", "va", "method", "RepoPutFile")
        .record(
            () -> {
              RepoPutFileReply reply = blockingStub().repoPutFile(request);
              if (!reply.getOk()) {
                throw Status.INTERNAL.withDescription(reply.getMsg()).asRuntimeException();
              }
              return null;
            });
  }

  @CircuitBreaker(name = "va")
  public String repoConvertUpload(String model, String version, byte[] onnxBytes)
      throws StatusRuntimeException {
    RepoConvertUploadRequest request =
        RepoConvertUploadRequest.newBuilder()
            .setModel(model)
            .setVersion(version)
            .setOnnx(ByteString.copyFrom(onnxBytes))
            .build();
    return meterRegistry
        .timer("cp.grpc.client", "svc", "va", "method", "RepoConvertUpload")
        .record(
            () -> {
              RepoConvertUploadReply reply = blockingStub().repoConvertUpload(request);
              return reply.getJobId();
            });
  }

  @CircuitBreaker(name = "va")
  public void repoConvertCancel(String jobId) throws StatusRuntimeException {
    RepoConvertCancelRequest request =
        RepoConvertCancelRequest.newBuilder().setJobId(jobId).build();
    meterRegistry
        .timer("cp.grpc.client", "svc", "va", "method", "RepoConvertCancel")
        .record(
            () -> {
              RepoConvertCancelReply unused = blockingStub().repoConvertCancel(request);
            });
  }

  @CircuitBreaker(name = "va")
  public java.util.Iterator<RepoConvertEvent> repoConvertStream(String jobId)
      throws StatusRuntimeException {
    RepoConvertStreamRequest request =
        RepoConvertStreamRequest.newBuilder().setJobId(jobId).build();
    meterRegistry
        .counter("cp.grpc.client.stream.open", "svc", "va", "method", "RepoConvertStream")
        .increment();
    return blockingStub().repoConvertStream(request);
  }

  @CircuitBreaker(name = "va")
  public void repoRemoveModel(String model) throws StatusRuntimeException {
    RepoRemoveModelRequest request =
        RepoRemoveModelRequest.newBuilder().setModel(model).build();
    meterRegistry
        .timer("cp.grpc.client", "svc", "va", "method", "RepoRemoveModel")
        .record(
            () -> {
              RepoRemoveModelReply reply = blockingStub().repoRemoveModel(request);
              if (!reply.getOk()) {
                throw Status.INTERNAL.withDescription(reply.getMsg()).asRuntimeException();
              }
              return null;
            });
  }
}
