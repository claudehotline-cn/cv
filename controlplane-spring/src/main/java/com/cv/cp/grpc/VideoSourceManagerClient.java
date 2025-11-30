package com.cv.cp.grpc;

import com.cv.cp.config.AppProperties;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import io.grpc.ManagedChannel;
import io.grpc.StatusRuntimeException;
import io.micrometer.core.instrument.MeterRegistry;
import java.util.Iterator;
import java.util.concurrent.TimeUnit;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Component;
import vsm.v1.AttachReply;
import vsm.v1.AttachRequest;
import vsm.v1.DetachReply;
import vsm.v1.DetachRequest;
import vsm.v1.GetHealthReply;
import vsm.v1.GetHealthRequest;
import vsm.v1.SourceControlGrpc;
import vsm.v1.SourceControlGrpc.SourceControlBlockingStub;
import vsm.v1.UpdateReply;
import vsm.v1.UpdateRequest;
import vsm.v1.WatchStateReply;
import vsm.v1.WatchStateRequest;

@Component
public class VideoSourceManagerClient {

  private final ManagedChannel channel;
  private final AppProperties properties;
  private final MeterRegistry meterRegistry;

  public VideoSourceManagerClient(
      @Qualifier("vsmChannel") ManagedChannel channel,
      AppProperties properties,
      MeterRegistry meterRegistry) {
    this.channel = channel;
    this.properties = properties;
    this.meterRegistry = meterRegistry;
  }

  private SourceControlBlockingStub unaryStub() {
    int timeoutMs =
        properties.getVsm() != null && properties.getVsm().getTimeoutMs() > 0
            ? properties.getVsm().getTimeoutMs()
            : 500;
    return SourceControlGrpc.newBlockingStub(channel)
        .withDeadlineAfter(timeoutMs, TimeUnit.MILLISECONDS);
  }

  private SourceControlBlockingStub streamingStub() {
    // 对于服务端流式调用不设置短 deadline，交由调用方控制生命周期
    return SourceControlGrpc.newBlockingStub(channel);
  }

  @CircuitBreaker(name = "vsm")
  public void attach(String attachId, String sourceUri, String pipelineId)
      throws StatusRuntimeException {
    AttachRequest request =
        AttachRequest.newBuilder()
            .setAttachId(attachId)
            .setSourceUri(sourceUri)
            .setPipelineId(pipelineId == null ? "" : pipelineId)
            .build();
    meterRegistry
        .timer("cp.grpc.client", "svc", "vsm", "method", "Attach")
        .record(
            () -> {
              AttachReply unused = unaryStub().attach(request);
            });
  }

  @CircuitBreaker(name = "vsm")
  public void detach(String attachId) throws StatusRuntimeException {
    DetachRequest request = DetachRequest.newBuilder().setAttachId(attachId).build();
    meterRegistry
        .timer("cp.grpc.client", "svc", "vsm", "method", "Detach")
        .record(
            () -> {
              DetachReply unused = unaryStub().detach(request);
            });
  }

  @CircuitBreaker(name = "vsm")
  public void setEnabled(String attachId, boolean enabled) throws StatusRuntimeException {
    UpdateRequest request =
        UpdateRequest.newBuilder()
            .setAttachId(attachId)
            .putOptions("enabled", enabled ? "true" : "false")
            .build();
    meterRegistry
        .timer("cp.grpc.client", "svc", "vsm", "method", "Update")
        .record(
            () -> {
              UpdateReply unused = unaryStub().update(request);
            });
  }

  @CircuitBreaker(name = "vsm")
  public GetHealthReply getHealth() throws StatusRuntimeException {
    GetHealthRequest request = GetHealthRequest.newBuilder().build();
    return meterRegistry
        .timer("cp.grpc.client", "svc", "vsm", "method", "GetHealth")
        .record(
            () -> unaryStub().getHealth(request));
  }

  /**
   * 打开 VSM 的 WatchState 流，返回迭代器由调用方消费。
   */
  @CircuitBreaker(name = "vsm")
  public Iterator<WatchStateReply> watchState(int intervalMs) throws StatusRuntimeException {
    WatchStateRequest request =
        WatchStateRequest.newBuilder().setIntervalMs(intervalMs).build();
    meterRegistry.counter("cp.grpc.client.stream.open", "svc", "vsm", "method", "WatchState")
        .increment();
    return streamingStub().watchState(request);
  }
}
