package com.cv.cp.grpc;

import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import io.grpc.ManagedChannel;
import io.grpc.StatusRuntimeException;
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

  public VideoSourceManagerClient(@Qualifier("vsmChannel") ManagedChannel channel) {
    this.channel = channel;
  }

  private SourceControlBlockingStub unaryStub() {
    return SourceControlGrpc.newBlockingStub(channel)
        .withDeadlineAfter(500, TimeUnit.MILLISECONDS);
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
    AttachReply unused = unaryStub().attach(request);
  }

  @CircuitBreaker(name = "vsm")
  public void detach(String attachId) throws StatusRuntimeException {
    DetachRequest request = DetachRequest.newBuilder().setAttachId(attachId).build();
    DetachReply unused = unaryStub().detach(request);
  }

  @CircuitBreaker(name = "vsm")
  public void setEnabled(String attachId, boolean enabled) throws StatusRuntimeException {
    UpdateRequest request =
        UpdateRequest.newBuilder()
            .setAttachId(attachId)
            .putOptions("enabled", enabled ? "true" : "false")
            .build();
    UpdateReply unused = unaryStub().update(request);
  }

  @CircuitBreaker(name = "vsm")
  public GetHealthReply getHealth() throws StatusRuntimeException {
    GetHealthRequest request = GetHealthRequest.newBuilder().build();
    return unaryStub().getHealth(request);
  }

  /**
   * 打开 VSM 的 WatchState 流，返回迭代器由调用方消费。
   */
  @CircuitBreaker(name = "vsm")
  public Iterator<WatchStateReply> watchState(int intervalMs) throws StatusRuntimeException {
    WatchStateRequest request =
        WatchStateRequest.newBuilder().setIntervalMs(intervalMs).build();
    return streamingStub().watchState(request);
  }
}
