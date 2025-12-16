package va.v1;

import static io.grpc.MethodDescriptor.generateFullMethodName;

/**
 * <pre>
 * 控制平面 → video-analyzer
 * </pre>
 */
@io.grpc.stub.annotations.GrpcGenerated
public final class AnalyzerControlGrpc {

  private AnalyzerControlGrpc() {}

  public static final java.lang.String SERVICE_NAME = "va.v1.AnalyzerControl";

  // Static method descriptors that strictly reflect the proto.
  private static volatile io.grpc.MethodDescriptor<va.v1.ApplyPipelineRequest,
      va.v1.ApplyPipelineReply> getApplyPipelineMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "ApplyPipeline",
      requestType = va.v1.ApplyPipelineRequest.class,
      responseType = va.v1.ApplyPipelineReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<va.v1.ApplyPipelineRequest,
      va.v1.ApplyPipelineReply> getApplyPipelineMethod() {
    io.grpc.MethodDescriptor<va.v1.ApplyPipelineRequest, va.v1.ApplyPipelineReply> getApplyPipelineMethod;
    if ((getApplyPipelineMethod = AnalyzerControlGrpc.getApplyPipelineMethod) == null) {
      synchronized (AnalyzerControlGrpc.class) {
        if ((getApplyPipelineMethod = AnalyzerControlGrpc.getApplyPipelineMethod) == null) {
          AnalyzerControlGrpc.getApplyPipelineMethod = getApplyPipelineMethod =
              io.grpc.MethodDescriptor.<va.v1.ApplyPipelineRequest, va.v1.ApplyPipelineReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "ApplyPipeline"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.ApplyPipelineRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.ApplyPipelineReply.getDefaultInstance()))
              .setSchemaDescriptor(new AnalyzerControlMethodDescriptorSupplier("ApplyPipeline"))
              .build();
        }
      }
    }
    return getApplyPipelineMethod;
  }

  private static volatile io.grpc.MethodDescriptor<va.v1.ApplyPipelinesRequest,
      va.v1.ApplyPipelinesReply> getApplyPipelinesMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "ApplyPipelines",
      requestType = va.v1.ApplyPipelinesRequest.class,
      responseType = va.v1.ApplyPipelinesReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<va.v1.ApplyPipelinesRequest,
      va.v1.ApplyPipelinesReply> getApplyPipelinesMethod() {
    io.grpc.MethodDescriptor<va.v1.ApplyPipelinesRequest, va.v1.ApplyPipelinesReply> getApplyPipelinesMethod;
    if ((getApplyPipelinesMethod = AnalyzerControlGrpc.getApplyPipelinesMethod) == null) {
      synchronized (AnalyzerControlGrpc.class) {
        if ((getApplyPipelinesMethod = AnalyzerControlGrpc.getApplyPipelinesMethod) == null) {
          AnalyzerControlGrpc.getApplyPipelinesMethod = getApplyPipelinesMethod =
              io.grpc.MethodDescriptor.<va.v1.ApplyPipelinesRequest, va.v1.ApplyPipelinesReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "ApplyPipelines"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.ApplyPipelinesRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.ApplyPipelinesReply.getDefaultInstance()))
              .setSchemaDescriptor(new AnalyzerControlMethodDescriptorSupplier("ApplyPipelines"))
              .build();
        }
      }
    }
    return getApplyPipelinesMethod;
  }

  private static volatile io.grpc.MethodDescriptor<va.v1.RemovePipelineRequest,
      va.v1.RemovePipelineReply> getRemovePipelineMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "RemovePipeline",
      requestType = va.v1.RemovePipelineRequest.class,
      responseType = va.v1.RemovePipelineReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<va.v1.RemovePipelineRequest,
      va.v1.RemovePipelineReply> getRemovePipelineMethod() {
    io.grpc.MethodDescriptor<va.v1.RemovePipelineRequest, va.v1.RemovePipelineReply> getRemovePipelineMethod;
    if ((getRemovePipelineMethod = AnalyzerControlGrpc.getRemovePipelineMethod) == null) {
      synchronized (AnalyzerControlGrpc.class) {
        if ((getRemovePipelineMethod = AnalyzerControlGrpc.getRemovePipelineMethod) == null) {
          AnalyzerControlGrpc.getRemovePipelineMethod = getRemovePipelineMethod =
              io.grpc.MethodDescriptor.<va.v1.RemovePipelineRequest, va.v1.RemovePipelineReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "RemovePipeline"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RemovePipelineRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RemovePipelineReply.getDefaultInstance()))
              .setSchemaDescriptor(new AnalyzerControlMethodDescriptorSupplier("RemovePipeline"))
              .build();
        }
      }
    }
    return getRemovePipelineMethod;
  }

  private static volatile io.grpc.MethodDescriptor<va.v1.HotSwapModelRequest,
      va.v1.HotSwapModelReply> getHotSwapModelMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "HotSwapModel",
      requestType = va.v1.HotSwapModelRequest.class,
      responseType = va.v1.HotSwapModelReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<va.v1.HotSwapModelRequest,
      va.v1.HotSwapModelReply> getHotSwapModelMethod() {
    io.grpc.MethodDescriptor<va.v1.HotSwapModelRequest, va.v1.HotSwapModelReply> getHotSwapModelMethod;
    if ((getHotSwapModelMethod = AnalyzerControlGrpc.getHotSwapModelMethod) == null) {
      synchronized (AnalyzerControlGrpc.class) {
        if ((getHotSwapModelMethod = AnalyzerControlGrpc.getHotSwapModelMethod) == null) {
          AnalyzerControlGrpc.getHotSwapModelMethod = getHotSwapModelMethod =
              io.grpc.MethodDescriptor.<va.v1.HotSwapModelRequest, va.v1.HotSwapModelReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "HotSwapModel"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.HotSwapModelRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.HotSwapModelReply.getDefaultInstance()))
              .setSchemaDescriptor(new AnalyzerControlMethodDescriptorSupplier("HotSwapModel"))
              .build();
        }
      }
    }
    return getHotSwapModelMethod;
  }

  private static volatile io.grpc.MethodDescriptor<va.v1.DrainRequest,
      va.v1.DrainReply> getDrainMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "Drain",
      requestType = va.v1.DrainRequest.class,
      responseType = va.v1.DrainReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<va.v1.DrainRequest,
      va.v1.DrainReply> getDrainMethod() {
    io.grpc.MethodDescriptor<va.v1.DrainRequest, va.v1.DrainReply> getDrainMethod;
    if ((getDrainMethod = AnalyzerControlGrpc.getDrainMethod) == null) {
      synchronized (AnalyzerControlGrpc.class) {
        if ((getDrainMethod = AnalyzerControlGrpc.getDrainMethod) == null) {
          AnalyzerControlGrpc.getDrainMethod = getDrainMethod =
              io.grpc.MethodDescriptor.<va.v1.DrainRequest, va.v1.DrainReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "Drain"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.DrainRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.DrainReply.getDefaultInstance()))
              .setSchemaDescriptor(new AnalyzerControlMethodDescriptorSupplier("Drain"))
              .build();
        }
      }
    }
    return getDrainMethod;
  }

  private static volatile io.grpc.MethodDescriptor<va.v1.GetStatusRequest,
      va.v1.GetStatusReply> getGetStatusMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "GetStatus",
      requestType = va.v1.GetStatusRequest.class,
      responseType = va.v1.GetStatusReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<va.v1.GetStatusRequest,
      va.v1.GetStatusReply> getGetStatusMethod() {
    io.grpc.MethodDescriptor<va.v1.GetStatusRequest, va.v1.GetStatusReply> getGetStatusMethod;
    if ((getGetStatusMethod = AnalyzerControlGrpc.getGetStatusMethod) == null) {
      synchronized (AnalyzerControlGrpc.class) {
        if ((getGetStatusMethod = AnalyzerControlGrpc.getGetStatusMethod) == null) {
          AnalyzerControlGrpc.getGetStatusMethod = getGetStatusMethod =
              io.grpc.MethodDescriptor.<va.v1.GetStatusRequest, va.v1.GetStatusReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "GetStatus"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.GetStatusRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.GetStatusReply.getDefaultInstance()))
              .setSchemaDescriptor(new AnalyzerControlMethodDescriptorSupplier("GetStatus"))
              .build();
        }
      }
    }
    return getGetStatusMethod;
  }

  private static volatile io.grpc.MethodDescriptor<va.v1.SubscribePipelineRequest,
      va.v1.SubscribePipelineReply> getSubscribePipelineMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "SubscribePipeline",
      requestType = va.v1.SubscribePipelineRequest.class,
      responseType = va.v1.SubscribePipelineReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<va.v1.SubscribePipelineRequest,
      va.v1.SubscribePipelineReply> getSubscribePipelineMethod() {
    io.grpc.MethodDescriptor<va.v1.SubscribePipelineRequest, va.v1.SubscribePipelineReply> getSubscribePipelineMethod;
    if ((getSubscribePipelineMethod = AnalyzerControlGrpc.getSubscribePipelineMethod) == null) {
      synchronized (AnalyzerControlGrpc.class) {
        if ((getSubscribePipelineMethod = AnalyzerControlGrpc.getSubscribePipelineMethod) == null) {
          AnalyzerControlGrpc.getSubscribePipelineMethod = getSubscribePipelineMethod =
              io.grpc.MethodDescriptor.<va.v1.SubscribePipelineRequest, va.v1.SubscribePipelineReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "SubscribePipeline"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.SubscribePipelineRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.SubscribePipelineReply.getDefaultInstance()))
              .setSchemaDescriptor(new AnalyzerControlMethodDescriptorSupplier("SubscribePipeline"))
              .build();
        }
      }
    }
    return getSubscribePipelineMethod;
  }

  private static volatile io.grpc.MethodDescriptor<va.v1.UnsubscribePipelineRequest,
      va.v1.UnsubscribePipelineReply> getUnsubscribePipelineMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "UnsubscribePipeline",
      requestType = va.v1.UnsubscribePipelineRequest.class,
      responseType = va.v1.UnsubscribePipelineReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<va.v1.UnsubscribePipelineRequest,
      va.v1.UnsubscribePipelineReply> getUnsubscribePipelineMethod() {
    io.grpc.MethodDescriptor<va.v1.UnsubscribePipelineRequest, va.v1.UnsubscribePipelineReply> getUnsubscribePipelineMethod;
    if ((getUnsubscribePipelineMethod = AnalyzerControlGrpc.getUnsubscribePipelineMethod) == null) {
      synchronized (AnalyzerControlGrpc.class) {
        if ((getUnsubscribePipelineMethod = AnalyzerControlGrpc.getUnsubscribePipelineMethod) == null) {
          AnalyzerControlGrpc.getUnsubscribePipelineMethod = getUnsubscribePipelineMethod =
              io.grpc.MethodDescriptor.<va.v1.UnsubscribePipelineRequest, va.v1.UnsubscribePipelineReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "UnsubscribePipeline"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.UnsubscribePipelineRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.UnsubscribePipelineReply.getDefaultInstance()))
              .setSchemaDescriptor(new AnalyzerControlMethodDescriptorSupplier("UnsubscribePipeline"))
              .build();
        }
      }
    }
    return getUnsubscribePipelineMethod;
  }

  private static volatile io.grpc.MethodDescriptor<va.v1.SetEngineRequest,
      va.v1.SetEngineReply> getSetEngineMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "SetEngine",
      requestType = va.v1.SetEngineRequest.class,
      responseType = va.v1.SetEngineReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<va.v1.SetEngineRequest,
      va.v1.SetEngineReply> getSetEngineMethod() {
    io.grpc.MethodDescriptor<va.v1.SetEngineRequest, va.v1.SetEngineReply> getSetEngineMethod;
    if ((getSetEngineMethod = AnalyzerControlGrpc.getSetEngineMethod) == null) {
      synchronized (AnalyzerControlGrpc.class) {
        if ((getSetEngineMethod = AnalyzerControlGrpc.getSetEngineMethod) == null) {
          AnalyzerControlGrpc.getSetEngineMethod = getSetEngineMethod =
              io.grpc.MethodDescriptor.<va.v1.SetEngineRequest, va.v1.SetEngineReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "SetEngine"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.SetEngineRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.SetEngineReply.getDefaultInstance()))
              .setSchemaDescriptor(new AnalyzerControlMethodDescriptorSupplier("SetEngine"))
              .build();
        }
      }
    }
    return getSetEngineMethod;
  }

  private static volatile io.grpc.MethodDescriptor<va.v1.QueryRuntimeRequest,
      va.v1.QueryRuntimeReply> getQueryRuntimeMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "QueryRuntime",
      requestType = va.v1.QueryRuntimeRequest.class,
      responseType = va.v1.QueryRuntimeReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<va.v1.QueryRuntimeRequest,
      va.v1.QueryRuntimeReply> getQueryRuntimeMethod() {
    io.grpc.MethodDescriptor<va.v1.QueryRuntimeRequest, va.v1.QueryRuntimeReply> getQueryRuntimeMethod;
    if ((getQueryRuntimeMethod = AnalyzerControlGrpc.getQueryRuntimeMethod) == null) {
      synchronized (AnalyzerControlGrpc.class) {
        if ((getQueryRuntimeMethod = AnalyzerControlGrpc.getQueryRuntimeMethod) == null) {
          AnalyzerControlGrpc.getQueryRuntimeMethod = getQueryRuntimeMethod =
              io.grpc.MethodDescriptor.<va.v1.QueryRuntimeRequest, va.v1.QueryRuntimeReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "QueryRuntime"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.QueryRuntimeRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.QueryRuntimeReply.getDefaultInstance()))
              .setSchemaDescriptor(new AnalyzerControlMethodDescriptorSupplier("QueryRuntime"))
              .build();
        }
      }
    }
    return getQueryRuntimeMethod;
  }

  private static volatile io.grpc.MethodDescriptor<va.v1.ListPipelinesRequest,
      va.v1.ListPipelinesReply> getListPipelinesMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "ListPipelines",
      requestType = va.v1.ListPipelinesRequest.class,
      responseType = va.v1.ListPipelinesReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<va.v1.ListPipelinesRequest,
      va.v1.ListPipelinesReply> getListPipelinesMethod() {
    io.grpc.MethodDescriptor<va.v1.ListPipelinesRequest, va.v1.ListPipelinesReply> getListPipelinesMethod;
    if ((getListPipelinesMethod = AnalyzerControlGrpc.getListPipelinesMethod) == null) {
      synchronized (AnalyzerControlGrpc.class) {
        if ((getListPipelinesMethod = AnalyzerControlGrpc.getListPipelinesMethod) == null) {
          AnalyzerControlGrpc.getListPipelinesMethod = getListPipelinesMethod =
              io.grpc.MethodDescriptor.<va.v1.ListPipelinesRequest, va.v1.ListPipelinesReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "ListPipelines"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.ListPipelinesRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.ListPipelinesReply.getDefaultInstance()))
              .setSchemaDescriptor(new AnalyzerControlMethodDescriptorSupplier("ListPipelines"))
              .build();
        }
      }
    }
    return getListPipelinesMethod;
  }

  private static volatile io.grpc.MethodDescriptor<va.v1.WatchRequest,
      va.v1.PhaseEvent> getWatchMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "Watch",
      requestType = va.v1.WatchRequest.class,
      responseType = va.v1.PhaseEvent.class,
      methodType = io.grpc.MethodDescriptor.MethodType.SERVER_STREAMING)
  public static io.grpc.MethodDescriptor<va.v1.WatchRequest,
      va.v1.PhaseEvent> getWatchMethod() {
    io.grpc.MethodDescriptor<va.v1.WatchRequest, va.v1.PhaseEvent> getWatchMethod;
    if ((getWatchMethod = AnalyzerControlGrpc.getWatchMethod) == null) {
      synchronized (AnalyzerControlGrpc.class) {
        if ((getWatchMethod = AnalyzerControlGrpc.getWatchMethod) == null) {
          AnalyzerControlGrpc.getWatchMethod = getWatchMethod =
              io.grpc.MethodDescriptor.<va.v1.WatchRequest, va.v1.PhaseEvent>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.SERVER_STREAMING)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "Watch"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.WatchRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.PhaseEvent.getDefaultInstance()))
              .setSchemaDescriptor(new AnalyzerControlMethodDescriptorSupplier("Watch"))
              .build();
        }
      }
    }
    return getWatchMethod;
  }

  private static volatile io.grpc.MethodDescriptor<va.v1.RepoLoadRequest,
      va.v1.RepoLoadReply> getRepoLoadMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "RepoLoad",
      requestType = va.v1.RepoLoadRequest.class,
      responseType = va.v1.RepoLoadReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<va.v1.RepoLoadRequest,
      va.v1.RepoLoadReply> getRepoLoadMethod() {
    io.grpc.MethodDescriptor<va.v1.RepoLoadRequest, va.v1.RepoLoadReply> getRepoLoadMethod;
    if ((getRepoLoadMethod = AnalyzerControlGrpc.getRepoLoadMethod) == null) {
      synchronized (AnalyzerControlGrpc.class) {
        if ((getRepoLoadMethod = AnalyzerControlGrpc.getRepoLoadMethod) == null) {
          AnalyzerControlGrpc.getRepoLoadMethod = getRepoLoadMethod =
              io.grpc.MethodDescriptor.<va.v1.RepoLoadRequest, va.v1.RepoLoadReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "RepoLoad"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RepoLoadRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RepoLoadReply.getDefaultInstance()))
              .setSchemaDescriptor(new AnalyzerControlMethodDescriptorSupplier("RepoLoad"))
              .build();
        }
      }
    }
    return getRepoLoadMethod;
  }

  private static volatile io.grpc.MethodDescriptor<va.v1.RepoUnloadRequest,
      va.v1.RepoUnloadReply> getRepoUnloadMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "RepoUnload",
      requestType = va.v1.RepoUnloadRequest.class,
      responseType = va.v1.RepoUnloadReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<va.v1.RepoUnloadRequest,
      va.v1.RepoUnloadReply> getRepoUnloadMethod() {
    io.grpc.MethodDescriptor<va.v1.RepoUnloadRequest, va.v1.RepoUnloadReply> getRepoUnloadMethod;
    if ((getRepoUnloadMethod = AnalyzerControlGrpc.getRepoUnloadMethod) == null) {
      synchronized (AnalyzerControlGrpc.class) {
        if ((getRepoUnloadMethod = AnalyzerControlGrpc.getRepoUnloadMethod) == null) {
          AnalyzerControlGrpc.getRepoUnloadMethod = getRepoUnloadMethod =
              io.grpc.MethodDescriptor.<va.v1.RepoUnloadRequest, va.v1.RepoUnloadReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "RepoUnload"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RepoUnloadRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RepoUnloadReply.getDefaultInstance()))
              .setSchemaDescriptor(new AnalyzerControlMethodDescriptorSupplier("RepoUnload"))
              .build();
        }
      }
    }
    return getRepoUnloadMethod;
  }

  private static volatile io.grpc.MethodDescriptor<va.v1.RepoPollRequest,
      va.v1.RepoPollReply> getRepoPollMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "RepoPoll",
      requestType = va.v1.RepoPollRequest.class,
      responseType = va.v1.RepoPollReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<va.v1.RepoPollRequest,
      va.v1.RepoPollReply> getRepoPollMethod() {
    io.grpc.MethodDescriptor<va.v1.RepoPollRequest, va.v1.RepoPollReply> getRepoPollMethod;
    if ((getRepoPollMethod = AnalyzerControlGrpc.getRepoPollMethod) == null) {
      synchronized (AnalyzerControlGrpc.class) {
        if ((getRepoPollMethod = AnalyzerControlGrpc.getRepoPollMethod) == null) {
          AnalyzerControlGrpc.getRepoPollMethod = getRepoPollMethod =
              io.grpc.MethodDescriptor.<va.v1.RepoPollRequest, va.v1.RepoPollReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "RepoPoll"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RepoPollRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RepoPollReply.getDefaultInstance()))
              .setSchemaDescriptor(new AnalyzerControlMethodDescriptorSupplier("RepoPoll"))
              .build();
        }
      }
    }
    return getRepoPollMethod;
  }

  private static volatile io.grpc.MethodDescriptor<va.v1.RepoListRequest,
      va.v1.RepoListReply> getRepoListMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "RepoList",
      requestType = va.v1.RepoListRequest.class,
      responseType = va.v1.RepoListReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<va.v1.RepoListRequest,
      va.v1.RepoListReply> getRepoListMethod() {
    io.grpc.MethodDescriptor<va.v1.RepoListRequest, va.v1.RepoListReply> getRepoListMethod;
    if ((getRepoListMethod = AnalyzerControlGrpc.getRepoListMethod) == null) {
      synchronized (AnalyzerControlGrpc.class) {
        if ((getRepoListMethod = AnalyzerControlGrpc.getRepoListMethod) == null) {
          AnalyzerControlGrpc.getRepoListMethod = getRepoListMethod =
              io.grpc.MethodDescriptor.<va.v1.RepoListRequest, va.v1.RepoListReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "RepoList"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RepoListRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RepoListReply.getDefaultInstance()))
              .setSchemaDescriptor(new AnalyzerControlMethodDescriptorSupplier("RepoList"))
              .build();
        }
      }
    }
    return getRepoListMethod;
  }

  private static volatile io.grpc.MethodDescriptor<va.v1.RepoGetConfigRequest,
      va.v1.RepoGetConfigReply> getRepoGetConfigMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "RepoGetConfig",
      requestType = va.v1.RepoGetConfigRequest.class,
      responseType = va.v1.RepoGetConfigReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<va.v1.RepoGetConfigRequest,
      va.v1.RepoGetConfigReply> getRepoGetConfigMethod() {
    io.grpc.MethodDescriptor<va.v1.RepoGetConfigRequest, va.v1.RepoGetConfigReply> getRepoGetConfigMethod;
    if ((getRepoGetConfigMethod = AnalyzerControlGrpc.getRepoGetConfigMethod) == null) {
      synchronized (AnalyzerControlGrpc.class) {
        if ((getRepoGetConfigMethod = AnalyzerControlGrpc.getRepoGetConfigMethod) == null) {
          AnalyzerControlGrpc.getRepoGetConfigMethod = getRepoGetConfigMethod =
              io.grpc.MethodDescriptor.<va.v1.RepoGetConfigRequest, va.v1.RepoGetConfigReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "RepoGetConfig"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RepoGetConfigRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RepoGetConfigReply.getDefaultInstance()))
              .setSchemaDescriptor(new AnalyzerControlMethodDescriptorSupplier("RepoGetConfig"))
              .build();
        }
      }
    }
    return getRepoGetConfigMethod;
  }

  private static volatile io.grpc.MethodDescriptor<va.v1.RepoSaveConfigRequest,
      va.v1.RepoSaveConfigReply> getRepoSaveConfigMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "RepoSaveConfig",
      requestType = va.v1.RepoSaveConfigRequest.class,
      responseType = va.v1.RepoSaveConfigReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<va.v1.RepoSaveConfigRequest,
      va.v1.RepoSaveConfigReply> getRepoSaveConfigMethod() {
    io.grpc.MethodDescriptor<va.v1.RepoSaveConfigRequest, va.v1.RepoSaveConfigReply> getRepoSaveConfigMethod;
    if ((getRepoSaveConfigMethod = AnalyzerControlGrpc.getRepoSaveConfigMethod) == null) {
      synchronized (AnalyzerControlGrpc.class) {
        if ((getRepoSaveConfigMethod = AnalyzerControlGrpc.getRepoSaveConfigMethod) == null) {
          AnalyzerControlGrpc.getRepoSaveConfigMethod = getRepoSaveConfigMethod =
              io.grpc.MethodDescriptor.<va.v1.RepoSaveConfigRequest, va.v1.RepoSaveConfigReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "RepoSaveConfig"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RepoSaveConfigRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RepoSaveConfigReply.getDefaultInstance()))
              .setSchemaDescriptor(new AnalyzerControlMethodDescriptorSupplier("RepoSaveConfig"))
              .build();
        }
      }
    }
    return getRepoSaveConfigMethod;
  }

  private static volatile io.grpc.MethodDescriptor<va.v1.RepoPutFileRequest,
      va.v1.RepoPutFileReply> getRepoPutFileMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "RepoPutFile",
      requestType = va.v1.RepoPutFileRequest.class,
      responseType = va.v1.RepoPutFileReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<va.v1.RepoPutFileRequest,
      va.v1.RepoPutFileReply> getRepoPutFileMethod() {
    io.grpc.MethodDescriptor<va.v1.RepoPutFileRequest, va.v1.RepoPutFileReply> getRepoPutFileMethod;
    if ((getRepoPutFileMethod = AnalyzerControlGrpc.getRepoPutFileMethod) == null) {
      synchronized (AnalyzerControlGrpc.class) {
        if ((getRepoPutFileMethod = AnalyzerControlGrpc.getRepoPutFileMethod) == null) {
          AnalyzerControlGrpc.getRepoPutFileMethod = getRepoPutFileMethod =
              io.grpc.MethodDescriptor.<va.v1.RepoPutFileRequest, va.v1.RepoPutFileReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "RepoPutFile"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RepoPutFileRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RepoPutFileReply.getDefaultInstance()))
              .setSchemaDescriptor(new AnalyzerControlMethodDescriptorSupplier("RepoPutFile"))
              .build();
        }
      }
    }
    return getRepoPutFileMethod;
  }

  private static volatile io.grpc.MethodDescriptor<va.v1.RepoConvertUploadRequest,
      va.v1.RepoConvertUploadReply> getRepoConvertUploadMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "RepoConvertUpload",
      requestType = va.v1.RepoConvertUploadRequest.class,
      responseType = va.v1.RepoConvertUploadReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<va.v1.RepoConvertUploadRequest,
      va.v1.RepoConvertUploadReply> getRepoConvertUploadMethod() {
    io.grpc.MethodDescriptor<va.v1.RepoConvertUploadRequest, va.v1.RepoConvertUploadReply> getRepoConvertUploadMethod;
    if ((getRepoConvertUploadMethod = AnalyzerControlGrpc.getRepoConvertUploadMethod) == null) {
      synchronized (AnalyzerControlGrpc.class) {
        if ((getRepoConvertUploadMethod = AnalyzerControlGrpc.getRepoConvertUploadMethod) == null) {
          AnalyzerControlGrpc.getRepoConvertUploadMethod = getRepoConvertUploadMethod =
              io.grpc.MethodDescriptor.<va.v1.RepoConvertUploadRequest, va.v1.RepoConvertUploadReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "RepoConvertUpload"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RepoConvertUploadRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RepoConvertUploadReply.getDefaultInstance()))
              .setSchemaDescriptor(new AnalyzerControlMethodDescriptorSupplier("RepoConvertUpload"))
              .build();
        }
      }
    }
    return getRepoConvertUploadMethod;
  }

  private static volatile io.grpc.MethodDescriptor<va.v1.RepoConvertStreamRequest,
      va.v1.RepoConvertEvent> getRepoConvertStreamMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "RepoConvertStream",
      requestType = va.v1.RepoConvertStreamRequest.class,
      responseType = va.v1.RepoConvertEvent.class,
      methodType = io.grpc.MethodDescriptor.MethodType.SERVER_STREAMING)
  public static io.grpc.MethodDescriptor<va.v1.RepoConvertStreamRequest,
      va.v1.RepoConvertEvent> getRepoConvertStreamMethod() {
    io.grpc.MethodDescriptor<va.v1.RepoConvertStreamRequest, va.v1.RepoConvertEvent> getRepoConvertStreamMethod;
    if ((getRepoConvertStreamMethod = AnalyzerControlGrpc.getRepoConvertStreamMethod) == null) {
      synchronized (AnalyzerControlGrpc.class) {
        if ((getRepoConvertStreamMethod = AnalyzerControlGrpc.getRepoConvertStreamMethod) == null) {
          AnalyzerControlGrpc.getRepoConvertStreamMethod = getRepoConvertStreamMethod =
              io.grpc.MethodDescriptor.<va.v1.RepoConvertStreamRequest, va.v1.RepoConvertEvent>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.SERVER_STREAMING)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "RepoConvertStream"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RepoConvertStreamRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RepoConvertEvent.getDefaultInstance()))
              .setSchemaDescriptor(new AnalyzerControlMethodDescriptorSupplier("RepoConvertStream"))
              .build();
        }
      }
    }
    return getRepoConvertStreamMethod;
  }

  private static volatile io.grpc.MethodDescriptor<va.v1.RepoConvertCancelRequest,
      va.v1.RepoConvertCancelReply> getRepoConvertCancelMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "RepoConvertCancel",
      requestType = va.v1.RepoConvertCancelRequest.class,
      responseType = va.v1.RepoConvertCancelReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<va.v1.RepoConvertCancelRequest,
      va.v1.RepoConvertCancelReply> getRepoConvertCancelMethod() {
    io.grpc.MethodDescriptor<va.v1.RepoConvertCancelRequest, va.v1.RepoConvertCancelReply> getRepoConvertCancelMethod;
    if ((getRepoConvertCancelMethod = AnalyzerControlGrpc.getRepoConvertCancelMethod) == null) {
      synchronized (AnalyzerControlGrpc.class) {
        if ((getRepoConvertCancelMethod = AnalyzerControlGrpc.getRepoConvertCancelMethod) == null) {
          AnalyzerControlGrpc.getRepoConvertCancelMethod = getRepoConvertCancelMethod =
              io.grpc.MethodDescriptor.<va.v1.RepoConvertCancelRequest, va.v1.RepoConvertCancelReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "RepoConvertCancel"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RepoConvertCancelRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RepoConvertCancelReply.getDefaultInstance()))
              .setSchemaDescriptor(new AnalyzerControlMethodDescriptorSupplier("RepoConvertCancel"))
              .build();
        }
      }
    }
    return getRepoConvertCancelMethod;
  }

  private static volatile io.grpc.MethodDescriptor<va.v1.RepoRemoveModelRequest,
      va.v1.RepoRemoveModelReply> getRepoRemoveModelMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "RepoRemoveModel",
      requestType = va.v1.RepoRemoveModelRequest.class,
      responseType = va.v1.RepoRemoveModelReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<va.v1.RepoRemoveModelRequest,
      va.v1.RepoRemoveModelReply> getRepoRemoveModelMethod() {
    io.grpc.MethodDescriptor<va.v1.RepoRemoveModelRequest, va.v1.RepoRemoveModelReply> getRepoRemoveModelMethod;
    if ((getRepoRemoveModelMethod = AnalyzerControlGrpc.getRepoRemoveModelMethod) == null) {
      synchronized (AnalyzerControlGrpc.class) {
        if ((getRepoRemoveModelMethod = AnalyzerControlGrpc.getRepoRemoveModelMethod) == null) {
          AnalyzerControlGrpc.getRepoRemoveModelMethod = getRepoRemoveModelMethod =
              io.grpc.MethodDescriptor.<va.v1.RepoRemoveModelRequest, va.v1.RepoRemoveModelReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "RepoRemoveModel"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RepoRemoveModelRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  va.v1.RepoRemoveModelReply.getDefaultInstance()))
              .setSchemaDescriptor(new AnalyzerControlMethodDescriptorSupplier("RepoRemoveModel"))
              .build();
        }
      }
    }
    return getRepoRemoveModelMethod;
  }

  /**
   * Creates a new async stub that supports all call types for the service
   */
  public static AnalyzerControlStub newStub(io.grpc.Channel channel) {
    io.grpc.stub.AbstractStub.StubFactory<AnalyzerControlStub> factory =
      new io.grpc.stub.AbstractStub.StubFactory<AnalyzerControlStub>() {
        @java.lang.Override
        public AnalyzerControlStub newStub(io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
          return new AnalyzerControlStub(channel, callOptions);
        }
      };
    return AnalyzerControlStub.newStub(factory, channel);
  }

  /**
   * Creates a new blocking-style stub that supports all types of calls on the service
   */
  public static AnalyzerControlBlockingV2Stub newBlockingV2Stub(
      io.grpc.Channel channel) {
    io.grpc.stub.AbstractStub.StubFactory<AnalyzerControlBlockingV2Stub> factory =
      new io.grpc.stub.AbstractStub.StubFactory<AnalyzerControlBlockingV2Stub>() {
        @java.lang.Override
        public AnalyzerControlBlockingV2Stub newStub(io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
          return new AnalyzerControlBlockingV2Stub(channel, callOptions);
        }
      };
    return AnalyzerControlBlockingV2Stub.newStub(factory, channel);
  }

  /**
   * Creates a new blocking-style stub that supports unary and streaming output calls on the service
   */
  public static AnalyzerControlBlockingStub newBlockingStub(
      io.grpc.Channel channel) {
    io.grpc.stub.AbstractStub.StubFactory<AnalyzerControlBlockingStub> factory =
      new io.grpc.stub.AbstractStub.StubFactory<AnalyzerControlBlockingStub>() {
        @java.lang.Override
        public AnalyzerControlBlockingStub newStub(io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
          return new AnalyzerControlBlockingStub(channel, callOptions);
        }
      };
    return AnalyzerControlBlockingStub.newStub(factory, channel);
  }

  /**
   * Creates a new ListenableFuture-style stub that supports unary calls on the service
   */
  public static AnalyzerControlFutureStub newFutureStub(
      io.grpc.Channel channel) {
    io.grpc.stub.AbstractStub.StubFactory<AnalyzerControlFutureStub> factory =
      new io.grpc.stub.AbstractStub.StubFactory<AnalyzerControlFutureStub>() {
        @java.lang.Override
        public AnalyzerControlFutureStub newStub(io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
          return new AnalyzerControlFutureStub(channel, callOptions);
        }
      };
    return AnalyzerControlFutureStub.newStub(factory, channel);
  }

  /**
   * <pre>
   * 控制平面 → video-analyzer
   * </pre>
   */
  public interface AsyncService {

    /**
     */
    default void applyPipeline(va.v1.ApplyPipelineRequest request,
        io.grpc.stub.StreamObserver<va.v1.ApplyPipelineReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getApplyPipelineMethod(), responseObserver);
    }

    /**
     * <pre>
     * M3: 批量下发多个 Pipeline 规格
     * </pre>
     */
    default void applyPipelines(va.v1.ApplyPipelinesRequest request,
        io.grpc.stub.StreamObserver<va.v1.ApplyPipelinesReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getApplyPipelinesMethod(), responseObserver);
    }

    /**
     */
    default void removePipeline(va.v1.RemovePipelineRequest request,
        io.grpc.stub.StreamObserver<va.v1.RemovePipelineReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getRemovePipelineMethod(), responseObserver);
    }

    /**
     */
    default void hotSwapModel(va.v1.HotSwapModelRequest request,
        io.grpc.stub.StreamObserver<va.v1.HotSwapModelReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getHotSwapModelMethod(), responseObserver);
    }

    /**
     */
    default void drain(va.v1.DrainRequest request,
        io.grpc.stub.StreamObserver<va.v1.DrainReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getDrainMethod(), responseObserver);
    }

    /**
     */
    default void getStatus(va.v1.GetStatusRequest request,
        io.grpc.stub.StreamObserver<va.v1.GetStatusReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getGetStatusMethod(), responseObserver);
    }

    /**
     * <pre>
     * M1+: 控制数据面最小集
     * </pre>
     */
    default void subscribePipeline(va.v1.SubscribePipelineRequest request,
        io.grpc.stub.StreamObserver<va.v1.SubscribePipelineReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getSubscribePipelineMethod(), responseObserver);
    }

    /**
     */
    default void unsubscribePipeline(va.v1.UnsubscribePipelineRequest request,
        io.grpc.stub.StreamObserver<va.v1.UnsubscribePipelineReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getUnsubscribePipelineMethod(), responseObserver);
    }

    /**
     */
    default void setEngine(va.v1.SetEngineRequest request,
        io.grpc.stub.StreamObserver<va.v1.SetEngineReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getSetEngineMethod(), responseObserver);
    }

    /**
     */
    default void queryRuntime(va.v1.QueryRuntimeRequest request,
        io.grpc.stub.StreamObserver<va.v1.QueryRuntimeReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getQueryRuntimeMethod(), responseObserver);
    }

    /**
     */
    default void listPipelines(va.v1.ListPipelinesRequest request,
        io.grpc.stub.StreamObserver<va.v1.ListPipelinesReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getListPipelinesMethod(), responseObserver);
    }

    /**
     * <pre>
     * Watch phases of a subscription or stream (prototype)
     * </pre>
     */
    default void watch(va.v1.WatchRequest request,
        io.grpc.stub.StreamObserver<va.v1.PhaseEvent> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getWatchMethod(), responseObserver);
    }

    /**
     * <pre>
     * P1: Minimal Triton repository controls for in-process embedding
     * </pre>
     */
    default void repoLoad(va.v1.RepoLoadRequest request,
        io.grpc.stub.StreamObserver<va.v1.RepoLoadReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getRepoLoadMethod(), responseObserver);
    }

    /**
     */
    default void repoUnload(va.v1.RepoUnloadRequest request,
        io.grpc.stub.StreamObserver<va.v1.RepoUnloadReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getRepoUnloadMethod(), responseObserver);
    }

    /**
     */
    default void repoPoll(va.v1.RepoPollRequest request,
        io.grpc.stub.StreamObserver<va.v1.RepoPollReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getRepoPollMethod(), responseObserver);
    }

    /**
     * <pre>
     * List models visible in the repository (best-effort). When the repository
     * is remote (e.g., S3), this may return currently loaded models if full
     * index is not available.
     * </pre>
     */
    default void repoList(va.v1.RepoListRequest request,
        io.grpc.stub.StreamObserver<va.v1.RepoListReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getRepoListMethod(), responseObserver);
    }

    /**
     * <pre>
     * Get a model's config.pbtxt content (best-effort)
     * </pre>
     */
    default void repoGetConfig(va.v1.RepoGetConfigRequest request,
        io.grpc.stub.StreamObserver<va.v1.RepoGetConfigReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getRepoGetConfigMethod(), responseObserver);
    }

    /**
     * <pre>
     * Save a model's config.pbtxt content (best-effort)
     * </pre>
     */
    default void repoSaveConfig(va.v1.RepoSaveConfigRequest request,
        io.grpc.stub.StreamObserver<va.v1.RepoSaveConfigReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getRepoSaveConfigMethod(), responseObserver);
    }

    /**
     * <pre>
     * Upload a file into model repository (e.g., model.onnx or model.plan)
     * </pre>
     */
    default void repoPutFile(va.v1.RepoPutFileRequest request,
        io.grpc.stub.StreamObserver<va.v1.RepoPutFileReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getRepoPutFileMethod(), responseObserver);
    }

    /**
     * <pre>
     * Convert ONNX to TensorRT plan and upload into repository. Returns a job id.
     * </pre>
     */
    default void repoConvertUpload(va.v1.RepoConvertUploadRequest request,
        io.grpc.stub.StreamObserver<va.v1.RepoConvertUploadReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getRepoConvertUploadMethod(), responseObserver);
    }

    /**
     * <pre>
     * Stream conversion progress/logs for a job id.
     * </pre>
     */
    default void repoConvertStream(va.v1.RepoConvertStreamRequest request,
        io.grpc.stub.StreamObserver<va.v1.RepoConvertEvent> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getRepoConvertStreamMethod(), responseObserver);
    }

    /**
     * <pre>
     * Cancel a running conversion job (best-effort)
     * </pre>
     */
    default void repoConvertCancel(va.v1.RepoConvertCancelRequest request,
        io.grpc.stub.StreamObserver<va.v1.RepoConvertCancelReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getRepoConvertCancelMethod(), responseObserver);
    }

    /**
     * <pre>
     * Remove a model directory from repository (best-effort). Requires explicit unload before removal.
     * </pre>
     */
    default void repoRemoveModel(va.v1.RepoRemoveModelRequest request,
        io.grpc.stub.StreamObserver<va.v1.RepoRemoveModelReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getRepoRemoveModelMethod(), responseObserver);
    }
  }

  /**
   * Base class for the server implementation of the service AnalyzerControl.
   * <pre>
   * 控制平面 → video-analyzer
   * </pre>
   */
  public static abstract class AnalyzerControlImplBase
      implements io.grpc.BindableService, AsyncService {

    @java.lang.Override public final io.grpc.ServerServiceDefinition bindService() {
      return AnalyzerControlGrpc.bindService(this);
    }
  }

  /**
   * A stub to allow clients to do asynchronous rpc calls to service AnalyzerControl.
   * <pre>
   * 控制平面 → video-analyzer
   * </pre>
   */
  public static final class AnalyzerControlStub
      extends io.grpc.stub.AbstractAsyncStub<AnalyzerControlStub> {
    private AnalyzerControlStub(
        io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
      super(channel, callOptions);
    }

    @java.lang.Override
    protected AnalyzerControlStub build(
        io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
      return new AnalyzerControlStub(channel, callOptions);
    }

    /**
     */
    public void applyPipeline(va.v1.ApplyPipelineRequest request,
        io.grpc.stub.StreamObserver<va.v1.ApplyPipelineReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getApplyPipelineMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     * <pre>
     * M3: 批量下发多个 Pipeline 规格
     * </pre>
     */
    public void applyPipelines(va.v1.ApplyPipelinesRequest request,
        io.grpc.stub.StreamObserver<va.v1.ApplyPipelinesReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getApplyPipelinesMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     */
    public void removePipeline(va.v1.RemovePipelineRequest request,
        io.grpc.stub.StreamObserver<va.v1.RemovePipelineReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getRemovePipelineMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     */
    public void hotSwapModel(va.v1.HotSwapModelRequest request,
        io.grpc.stub.StreamObserver<va.v1.HotSwapModelReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getHotSwapModelMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     */
    public void drain(va.v1.DrainRequest request,
        io.grpc.stub.StreamObserver<va.v1.DrainReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getDrainMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     */
    public void getStatus(va.v1.GetStatusRequest request,
        io.grpc.stub.StreamObserver<va.v1.GetStatusReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getGetStatusMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     * <pre>
     * M1+: 控制数据面最小集
     * </pre>
     */
    public void subscribePipeline(va.v1.SubscribePipelineRequest request,
        io.grpc.stub.StreamObserver<va.v1.SubscribePipelineReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getSubscribePipelineMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     */
    public void unsubscribePipeline(va.v1.UnsubscribePipelineRequest request,
        io.grpc.stub.StreamObserver<va.v1.UnsubscribePipelineReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getUnsubscribePipelineMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     */
    public void setEngine(va.v1.SetEngineRequest request,
        io.grpc.stub.StreamObserver<va.v1.SetEngineReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getSetEngineMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     */
    public void queryRuntime(va.v1.QueryRuntimeRequest request,
        io.grpc.stub.StreamObserver<va.v1.QueryRuntimeReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getQueryRuntimeMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     */
    public void listPipelines(va.v1.ListPipelinesRequest request,
        io.grpc.stub.StreamObserver<va.v1.ListPipelinesReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getListPipelinesMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     * <pre>
     * Watch phases of a subscription or stream (prototype)
     * </pre>
     */
    public void watch(va.v1.WatchRequest request,
        io.grpc.stub.StreamObserver<va.v1.PhaseEvent> responseObserver) {
      io.grpc.stub.ClientCalls.asyncServerStreamingCall(
          getChannel().newCall(getWatchMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     * <pre>
     * P1: Minimal Triton repository controls for in-process embedding
     * </pre>
     */
    public void repoLoad(va.v1.RepoLoadRequest request,
        io.grpc.stub.StreamObserver<va.v1.RepoLoadReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getRepoLoadMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     */
    public void repoUnload(va.v1.RepoUnloadRequest request,
        io.grpc.stub.StreamObserver<va.v1.RepoUnloadReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getRepoUnloadMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     */
    public void repoPoll(va.v1.RepoPollRequest request,
        io.grpc.stub.StreamObserver<va.v1.RepoPollReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getRepoPollMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     * <pre>
     * List models visible in the repository (best-effort). When the repository
     * is remote (e.g., S3), this may return currently loaded models if full
     * index is not available.
     * </pre>
     */
    public void repoList(va.v1.RepoListRequest request,
        io.grpc.stub.StreamObserver<va.v1.RepoListReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getRepoListMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     * <pre>
     * Get a model's config.pbtxt content (best-effort)
     * </pre>
     */
    public void repoGetConfig(va.v1.RepoGetConfigRequest request,
        io.grpc.stub.StreamObserver<va.v1.RepoGetConfigReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getRepoGetConfigMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     * <pre>
     * Save a model's config.pbtxt content (best-effort)
     * </pre>
     */
    public void repoSaveConfig(va.v1.RepoSaveConfigRequest request,
        io.grpc.stub.StreamObserver<va.v1.RepoSaveConfigReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getRepoSaveConfigMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     * <pre>
     * Upload a file into model repository (e.g., model.onnx or model.plan)
     * </pre>
     */
    public void repoPutFile(va.v1.RepoPutFileRequest request,
        io.grpc.stub.StreamObserver<va.v1.RepoPutFileReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getRepoPutFileMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     * <pre>
     * Convert ONNX to TensorRT plan and upload into repository. Returns a job id.
     * </pre>
     */
    public void repoConvertUpload(va.v1.RepoConvertUploadRequest request,
        io.grpc.stub.StreamObserver<va.v1.RepoConvertUploadReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getRepoConvertUploadMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     * <pre>
     * Stream conversion progress/logs for a job id.
     * </pre>
     */
    public void repoConvertStream(va.v1.RepoConvertStreamRequest request,
        io.grpc.stub.StreamObserver<va.v1.RepoConvertEvent> responseObserver) {
      io.grpc.stub.ClientCalls.asyncServerStreamingCall(
          getChannel().newCall(getRepoConvertStreamMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     * <pre>
     * Cancel a running conversion job (best-effort)
     * </pre>
     */
    public void repoConvertCancel(va.v1.RepoConvertCancelRequest request,
        io.grpc.stub.StreamObserver<va.v1.RepoConvertCancelReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getRepoConvertCancelMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     * <pre>
     * Remove a model directory from repository (best-effort). Requires explicit unload before removal.
     * </pre>
     */
    public void repoRemoveModel(va.v1.RepoRemoveModelRequest request,
        io.grpc.stub.StreamObserver<va.v1.RepoRemoveModelReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getRepoRemoveModelMethod(), getCallOptions()), request, responseObserver);
    }
  }

  /**
   * A stub to allow clients to do synchronous rpc calls to service AnalyzerControl.
   * <pre>
   * 控制平面 → video-analyzer
   * </pre>
   */
  public static final class AnalyzerControlBlockingV2Stub
      extends io.grpc.stub.AbstractBlockingStub<AnalyzerControlBlockingV2Stub> {
    private AnalyzerControlBlockingV2Stub(
        io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
      super(channel, callOptions);
    }

    @java.lang.Override
    protected AnalyzerControlBlockingV2Stub build(
        io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
      return new AnalyzerControlBlockingV2Stub(channel, callOptions);
    }

    /**
     */
    public va.v1.ApplyPipelineReply applyPipeline(va.v1.ApplyPipelineRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getApplyPipelineMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * M3: 批量下发多个 Pipeline 规格
     * </pre>
     */
    public va.v1.ApplyPipelinesReply applyPipelines(va.v1.ApplyPipelinesRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getApplyPipelinesMethod(), getCallOptions(), request);
    }

    /**
     */
    public va.v1.RemovePipelineReply removePipeline(va.v1.RemovePipelineRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getRemovePipelineMethod(), getCallOptions(), request);
    }

    /**
     */
    public va.v1.HotSwapModelReply hotSwapModel(va.v1.HotSwapModelRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getHotSwapModelMethod(), getCallOptions(), request);
    }

    /**
     */
    public va.v1.DrainReply drain(va.v1.DrainRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getDrainMethod(), getCallOptions(), request);
    }

    /**
     */
    public va.v1.GetStatusReply getStatus(va.v1.GetStatusRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getGetStatusMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * M1+: 控制数据面最小集
     * </pre>
     */
    public va.v1.SubscribePipelineReply subscribePipeline(va.v1.SubscribePipelineRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getSubscribePipelineMethod(), getCallOptions(), request);
    }

    /**
     */
    public va.v1.UnsubscribePipelineReply unsubscribePipeline(va.v1.UnsubscribePipelineRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getUnsubscribePipelineMethod(), getCallOptions(), request);
    }

    /**
     */
    public va.v1.SetEngineReply setEngine(va.v1.SetEngineRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getSetEngineMethod(), getCallOptions(), request);
    }

    /**
     */
    public va.v1.QueryRuntimeReply queryRuntime(va.v1.QueryRuntimeRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getQueryRuntimeMethod(), getCallOptions(), request);
    }

    /**
     */
    public va.v1.ListPipelinesReply listPipelines(va.v1.ListPipelinesRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getListPipelinesMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * Watch phases of a subscription or stream (prototype)
     * </pre>
     */
    @io.grpc.ExperimentalApi("https://github.com/grpc/grpc-java/issues/10918")
    public io.grpc.stub.BlockingClientCall<?, va.v1.PhaseEvent>
        watch(va.v1.WatchRequest request) {
      return io.grpc.stub.ClientCalls.blockingV2ServerStreamingCall(
          getChannel(), getWatchMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * P1: Minimal Triton repository controls for in-process embedding
     * </pre>
     */
    public va.v1.RepoLoadReply repoLoad(va.v1.RepoLoadRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getRepoLoadMethod(), getCallOptions(), request);
    }

    /**
     */
    public va.v1.RepoUnloadReply repoUnload(va.v1.RepoUnloadRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getRepoUnloadMethod(), getCallOptions(), request);
    }

    /**
     */
    public va.v1.RepoPollReply repoPoll(va.v1.RepoPollRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getRepoPollMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * List models visible in the repository (best-effort). When the repository
     * is remote (e.g., S3), this may return currently loaded models if full
     * index is not available.
     * </pre>
     */
    public va.v1.RepoListReply repoList(va.v1.RepoListRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getRepoListMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * Get a model's config.pbtxt content (best-effort)
     * </pre>
     */
    public va.v1.RepoGetConfigReply repoGetConfig(va.v1.RepoGetConfigRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getRepoGetConfigMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * Save a model's config.pbtxt content (best-effort)
     * </pre>
     */
    public va.v1.RepoSaveConfigReply repoSaveConfig(va.v1.RepoSaveConfigRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getRepoSaveConfigMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * Upload a file into model repository (e.g., model.onnx or model.plan)
     * </pre>
     */
    public va.v1.RepoPutFileReply repoPutFile(va.v1.RepoPutFileRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getRepoPutFileMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * Convert ONNX to TensorRT plan and upload into repository. Returns a job id.
     * </pre>
     */
    public va.v1.RepoConvertUploadReply repoConvertUpload(va.v1.RepoConvertUploadRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getRepoConvertUploadMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * Stream conversion progress/logs for a job id.
     * </pre>
     */
    @io.grpc.ExperimentalApi("https://github.com/grpc/grpc-java/issues/10918")
    public io.grpc.stub.BlockingClientCall<?, va.v1.RepoConvertEvent>
        repoConvertStream(va.v1.RepoConvertStreamRequest request) {
      return io.grpc.stub.ClientCalls.blockingV2ServerStreamingCall(
          getChannel(), getRepoConvertStreamMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * Cancel a running conversion job (best-effort)
     * </pre>
     */
    public va.v1.RepoConvertCancelReply repoConvertCancel(va.v1.RepoConvertCancelRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getRepoConvertCancelMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * Remove a model directory from repository (best-effort). Requires explicit unload before removal.
     * </pre>
     */
    public va.v1.RepoRemoveModelReply repoRemoveModel(va.v1.RepoRemoveModelRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getRepoRemoveModelMethod(), getCallOptions(), request);
    }
  }

  /**
   * A stub to allow clients to do limited synchronous rpc calls to service AnalyzerControl.
   * <pre>
   * 控制平面 → video-analyzer
   * </pre>
   */
  public static final class AnalyzerControlBlockingStub
      extends io.grpc.stub.AbstractBlockingStub<AnalyzerControlBlockingStub> {
    private AnalyzerControlBlockingStub(
        io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
      super(channel, callOptions);
    }

    @java.lang.Override
    protected AnalyzerControlBlockingStub build(
        io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
      return new AnalyzerControlBlockingStub(channel, callOptions);
    }

    /**
     */
    public va.v1.ApplyPipelineReply applyPipeline(va.v1.ApplyPipelineRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getApplyPipelineMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * M3: 批量下发多个 Pipeline 规格
     * </pre>
     */
    public va.v1.ApplyPipelinesReply applyPipelines(va.v1.ApplyPipelinesRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getApplyPipelinesMethod(), getCallOptions(), request);
    }

    /**
     */
    public va.v1.RemovePipelineReply removePipeline(va.v1.RemovePipelineRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getRemovePipelineMethod(), getCallOptions(), request);
    }

    /**
     */
    public va.v1.HotSwapModelReply hotSwapModel(va.v1.HotSwapModelRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getHotSwapModelMethod(), getCallOptions(), request);
    }

    /**
     */
    public va.v1.DrainReply drain(va.v1.DrainRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getDrainMethod(), getCallOptions(), request);
    }

    /**
     */
    public va.v1.GetStatusReply getStatus(va.v1.GetStatusRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getGetStatusMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * M1+: 控制数据面最小集
     * </pre>
     */
    public va.v1.SubscribePipelineReply subscribePipeline(va.v1.SubscribePipelineRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getSubscribePipelineMethod(), getCallOptions(), request);
    }

    /**
     */
    public va.v1.UnsubscribePipelineReply unsubscribePipeline(va.v1.UnsubscribePipelineRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getUnsubscribePipelineMethod(), getCallOptions(), request);
    }

    /**
     */
    public va.v1.SetEngineReply setEngine(va.v1.SetEngineRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getSetEngineMethod(), getCallOptions(), request);
    }

    /**
     */
    public va.v1.QueryRuntimeReply queryRuntime(va.v1.QueryRuntimeRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getQueryRuntimeMethod(), getCallOptions(), request);
    }

    /**
     */
    public va.v1.ListPipelinesReply listPipelines(va.v1.ListPipelinesRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getListPipelinesMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * Watch phases of a subscription or stream (prototype)
     * </pre>
     */
    public java.util.Iterator<va.v1.PhaseEvent> watch(
        va.v1.WatchRequest request) {
      return io.grpc.stub.ClientCalls.blockingServerStreamingCall(
          getChannel(), getWatchMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * P1: Minimal Triton repository controls for in-process embedding
     * </pre>
     */
    public va.v1.RepoLoadReply repoLoad(va.v1.RepoLoadRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getRepoLoadMethod(), getCallOptions(), request);
    }

    /**
     */
    public va.v1.RepoUnloadReply repoUnload(va.v1.RepoUnloadRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getRepoUnloadMethod(), getCallOptions(), request);
    }

    /**
     */
    public va.v1.RepoPollReply repoPoll(va.v1.RepoPollRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getRepoPollMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * List models visible in the repository (best-effort). When the repository
     * is remote (e.g., S3), this may return currently loaded models if full
     * index is not available.
     * </pre>
     */
    public va.v1.RepoListReply repoList(va.v1.RepoListRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getRepoListMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * Get a model's config.pbtxt content (best-effort)
     * </pre>
     */
    public va.v1.RepoGetConfigReply repoGetConfig(va.v1.RepoGetConfigRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getRepoGetConfigMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * Save a model's config.pbtxt content (best-effort)
     * </pre>
     */
    public va.v1.RepoSaveConfigReply repoSaveConfig(va.v1.RepoSaveConfigRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getRepoSaveConfigMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * Upload a file into model repository (e.g., model.onnx or model.plan)
     * </pre>
     */
    public va.v1.RepoPutFileReply repoPutFile(va.v1.RepoPutFileRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getRepoPutFileMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * Convert ONNX to TensorRT plan and upload into repository. Returns a job id.
     * </pre>
     */
    public va.v1.RepoConvertUploadReply repoConvertUpload(va.v1.RepoConvertUploadRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getRepoConvertUploadMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * Stream conversion progress/logs for a job id.
     * </pre>
     */
    public java.util.Iterator<va.v1.RepoConvertEvent> repoConvertStream(
        va.v1.RepoConvertStreamRequest request) {
      return io.grpc.stub.ClientCalls.blockingServerStreamingCall(
          getChannel(), getRepoConvertStreamMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * Cancel a running conversion job (best-effort)
     * </pre>
     */
    public va.v1.RepoConvertCancelReply repoConvertCancel(va.v1.RepoConvertCancelRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getRepoConvertCancelMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * Remove a model directory from repository (best-effort). Requires explicit unload before removal.
     * </pre>
     */
    public va.v1.RepoRemoveModelReply repoRemoveModel(va.v1.RepoRemoveModelRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getRepoRemoveModelMethod(), getCallOptions(), request);
    }
  }

  /**
   * A stub to allow clients to do ListenableFuture-style rpc calls to service AnalyzerControl.
   * <pre>
   * 控制平面 → video-analyzer
   * </pre>
   */
  public static final class AnalyzerControlFutureStub
      extends io.grpc.stub.AbstractFutureStub<AnalyzerControlFutureStub> {
    private AnalyzerControlFutureStub(
        io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
      super(channel, callOptions);
    }

    @java.lang.Override
    protected AnalyzerControlFutureStub build(
        io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
      return new AnalyzerControlFutureStub(channel, callOptions);
    }

    /**
     */
    public com.google.common.util.concurrent.ListenableFuture<va.v1.ApplyPipelineReply> applyPipeline(
        va.v1.ApplyPipelineRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getApplyPipelineMethod(), getCallOptions()), request);
    }

    /**
     * <pre>
     * M3: 批量下发多个 Pipeline 规格
     * </pre>
     */
    public com.google.common.util.concurrent.ListenableFuture<va.v1.ApplyPipelinesReply> applyPipelines(
        va.v1.ApplyPipelinesRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getApplyPipelinesMethod(), getCallOptions()), request);
    }

    /**
     */
    public com.google.common.util.concurrent.ListenableFuture<va.v1.RemovePipelineReply> removePipeline(
        va.v1.RemovePipelineRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getRemovePipelineMethod(), getCallOptions()), request);
    }

    /**
     */
    public com.google.common.util.concurrent.ListenableFuture<va.v1.HotSwapModelReply> hotSwapModel(
        va.v1.HotSwapModelRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getHotSwapModelMethod(), getCallOptions()), request);
    }

    /**
     */
    public com.google.common.util.concurrent.ListenableFuture<va.v1.DrainReply> drain(
        va.v1.DrainRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getDrainMethod(), getCallOptions()), request);
    }

    /**
     */
    public com.google.common.util.concurrent.ListenableFuture<va.v1.GetStatusReply> getStatus(
        va.v1.GetStatusRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getGetStatusMethod(), getCallOptions()), request);
    }

    /**
     * <pre>
     * M1+: 控制数据面最小集
     * </pre>
     */
    public com.google.common.util.concurrent.ListenableFuture<va.v1.SubscribePipelineReply> subscribePipeline(
        va.v1.SubscribePipelineRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getSubscribePipelineMethod(), getCallOptions()), request);
    }

    /**
     */
    public com.google.common.util.concurrent.ListenableFuture<va.v1.UnsubscribePipelineReply> unsubscribePipeline(
        va.v1.UnsubscribePipelineRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getUnsubscribePipelineMethod(), getCallOptions()), request);
    }

    /**
     */
    public com.google.common.util.concurrent.ListenableFuture<va.v1.SetEngineReply> setEngine(
        va.v1.SetEngineRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getSetEngineMethod(), getCallOptions()), request);
    }

    /**
     */
    public com.google.common.util.concurrent.ListenableFuture<va.v1.QueryRuntimeReply> queryRuntime(
        va.v1.QueryRuntimeRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getQueryRuntimeMethod(), getCallOptions()), request);
    }

    /**
     */
    public com.google.common.util.concurrent.ListenableFuture<va.v1.ListPipelinesReply> listPipelines(
        va.v1.ListPipelinesRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getListPipelinesMethod(), getCallOptions()), request);
    }

    /**
     * <pre>
     * P1: Minimal Triton repository controls for in-process embedding
     * </pre>
     */
    public com.google.common.util.concurrent.ListenableFuture<va.v1.RepoLoadReply> repoLoad(
        va.v1.RepoLoadRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getRepoLoadMethod(), getCallOptions()), request);
    }

    /**
     */
    public com.google.common.util.concurrent.ListenableFuture<va.v1.RepoUnloadReply> repoUnload(
        va.v1.RepoUnloadRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getRepoUnloadMethod(), getCallOptions()), request);
    }

    /**
     */
    public com.google.common.util.concurrent.ListenableFuture<va.v1.RepoPollReply> repoPoll(
        va.v1.RepoPollRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getRepoPollMethod(), getCallOptions()), request);
    }

    /**
     * <pre>
     * List models visible in the repository (best-effort). When the repository
     * is remote (e.g., S3), this may return currently loaded models if full
     * index is not available.
     * </pre>
     */
    public com.google.common.util.concurrent.ListenableFuture<va.v1.RepoListReply> repoList(
        va.v1.RepoListRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getRepoListMethod(), getCallOptions()), request);
    }

    /**
     * <pre>
     * Get a model's config.pbtxt content (best-effort)
     * </pre>
     */
    public com.google.common.util.concurrent.ListenableFuture<va.v1.RepoGetConfigReply> repoGetConfig(
        va.v1.RepoGetConfigRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getRepoGetConfigMethod(), getCallOptions()), request);
    }

    /**
     * <pre>
     * Save a model's config.pbtxt content (best-effort)
     * </pre>
     */
    public com.google.common.util.concurrent.ListenableFuture<va.v1.RepoSaveConfigReply> repoSaveConfig(
        va.v1.RepoSaveConfigRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getRepoSaveConfigMethod(), getCallOptions()), request);
    }

    /**
     * <pre>
     * Upload a file into model repository (e.g., model.onnx or model.plan)
     * </pre>
     */
    public com.google.common.util.concurrent.ListenableFuture<va.v1.RepoPutFileReply> repoPutFile(
        va.v1.RepoPutFileRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getRepoPutFileMethod(), getCallOptions()), request);
    }

    /**
     * <pre>
     * Convert ONNX to TensorRT plan and upload into repository. Returns a job id.
     * </pre>
     */
    public com.google.common.util.concurrent.ListenableFuture<va.v1.RepoConvertUploadReply> repoConvertUpload(
        va.v1.RepoConvertUploadRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getRepoConvertUploadMethod(), getCallOptions()), request);
    }

    /**
     * <pre>
     * Cancel a running conversion job (best-effort)
     * </pre>
     */
    public com.google.common.util.concurrent.ListenableFuture<va.v1.RepoConvertCancelReply> repoConvertCancel(
        va.v1.RepoConvertCancelRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getRepoConvertCancelMethod(), getCallOptions()), request);
    }

    /**
     * <pre>
     * Remove a model directory from repository (best-effort). Requires explicit unload before removal.
     * </pre>
     */
    public com.google.common.util.concurrent.ListenableFuture<va.v1.RepoRemoveModelReply> repoRemoveModel(
        va.v1.RepoRemoveModelRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getRepoRemoveModelMethod(), getCallOptions()), request);
    }
  }

  private static final int METHODID_APPLY_PIPELINE = 0;
  private static final int METHODID_APPLY_PIPELINES = 1;
  private static final int METHODID_REMOVE_PIPELINE = 2;
  private static final int METHODID_HOT_SWAP_MODEL = 3;
  private static final int METHODID_DRAIN = 4;
  private static final int METHODID_GET_STATUS = 5;
  private static final int METHODID_SUBSCRIBE_PIPELINE = 6;
  private static final int METHODID_UNSUBSCRIBE_PIPELINE = 7;
  private static final int METHODID_SET_ENGINE = 8;
  private static final int METHODID_QUERY_RUNTIME = 9;
  private static final int METHODID_LIST_PIPELINES = 10;
  private static final int METHODID_WATCH = 11;
  private static final int METHODID_REPO_LOAD = 12;
  private static final int METHODID_REPO_UNLOAD = 13;
  private static final int METHODID_REPO_POLL = 14;
  private static final int METHODID_REPO_LIST = 15;
  private static final int METHODID_REPO_GET_CONFIG = 16;
  private static final int METHODID_REPO_SAVE_CONFIG = 17;
  private static final int METHODID_REPO_PUT_FILE = 18;
  private static final int METHODID_REPO_CONVERT_UPLOAD = 19;
  private static final int METHODID_REPO_CONVERT_STREAM = 20;
  private static final int METHODID_REPO_CONVERT_CANCEL = 21;
  private static final int METHODID_REPO_REMOVE_MODEL = 22;

  private static final class MethodHandlers<Req, Resp> implements
      io.grpc.stub.ServerCalls.UnaryMethod<Req, Resp>,
      io.grpc.stub.ServerCalls.ServerStreamingMethod<Req, Resp>,
      io.grpc.stub.ServerCalls.ClientStreamingMethod<Req, Resp>,
      io.grpc.stub.ServerCalls.BidiStreamingMethod<Req, Resp> {
    private final AsyncService serviceImpl;
    private final int methodId;

    MethodHandlers(AsyncService serviceImpl, int methodId) {
      this.serviceImpl = serviceImpl;
      this.methodId = methodId;
    }

    @java.lang.Override
    @java.lang.SuppressWarnings("unchecked")
    public void invoke(Req request, io.grpc.stub.StreamObserver<Resp> responseObserver) {
      switch (methodId) {
        case METHODID_APPLY_PIPELINE:
          serviceImpl.applyPipeline((va.v1.ApplyPipelineRequest) request,
              (io.grpc.stub.StreamObserver<va.v1.ApplyPipelineReply>) responseObserver);
          break;
        case METHODID_APPLY_PIPELINES:
          serviceImpl.applyPipelines((va.v1.ApplyPipelinesRequest) request,
              (io.grpc.stub.StreamObserver<va.v1.ApplyPipelinesReply>) responseObserver);
          break;
        case METHODID_REMOVE_PIPELINE:
          serviceImpl.removePipeline((va.v1.RemovePipelineRequest) request,
              (io.grpc.stub.StreamObserver<va.v1.RemovePipelineReply>) responseObserver);
          break;
        case METHODID_HOT_SWAP_MODEL:
          serviceImpl.hotSwapModel((va.v1.HotSwapModelRequest) request,
              (io.grpc.stub.StreamObserver<va.v1.HotSwapModelReply>) responseObserver);
          break;
        case METHODID_DRAIN:
          serviceImpl.drain((va.v1.DrainRequest) request,
              (io.grpc.stub.StreamObserver<va.v1.DrainReply>) responseObserver);
          break;
        case METHODID_GET_STATUS:
          serviceImpl.getStatus((va.v1.GetStatusRequest) request,
              (io.grpc.stub.StreamObserver<va.v1.GetStatusReply>) responseObserver);
          break;
        case METHODID_SUBSCRIBE_PIPELINE:
          serviceImpl.subscribePipeline((va.v1.SubscribePipelineRequest) request,
              (io.grpc.stub.StreamObserver<va.v1.SubscribePipelineReply>) responseObserver);
          break;
        case METHODID_UNSUBSCRIBE_PIPELINE:
          serviceImpl.unsubscribePipeline((va.v1.UnsubscribePipelineRequest) request,
              (io.grpc.stub.StreamObserver<va.v1.UnsubscribePipelineReply>) responseObserver);
          break;
        case METHODID_SET_ENGINE:
          serviceImpl.setEngine((va.v1.SetEngineRequest) request,
              (io.grpc.stub.StreamObserver<va.v1.SetEngineReply>) responseObserver);
          break;
        case METHODID_QUERY_RUNTIME:
          serviceImpl.queryRuntime((va.v1.QueryRuntimeRequest) request,
              (io.grpc.stub.StreamObserver<va.v1.QueryRuntimeReply>) responseObserver);
          break;
        case METHODID_LIST_PIPELINES:
          serviceImpl.listPipelines((va.v1.ListPipelinesRequest) request,
              (io.grpc.stub.StreamObserver<va.v1.ListPipelinesReply>) responseObserver);
          break;
        case METHODID_WATCH:
          serviceImpl.watch((va.v1.WatchRequest) request,
              (io.grpc.stub.StreamObserver<va.v1.PhaseEvent>) responseObserver);
          break;
        case METHODID_REPO_LOAD:
          serviceImpl.repoLoad((va.v1.RepoLoadRequest) request,
              (io.grpc.stub.StreamObserver<va.v1.RepoLoadReply>) responseObserver);
          break;
        case METHODID_REPO_UNLOAD:
          serviceImpl.repoUnload((va.v1.RepoUnloadRequest) request,
              (io.grpc.stub.StreamObserver<va.v1.RepoUnloadReply>) responseObserver);
          break;
        case METHODID_REPO_POLL:
          serviceImpl.repoPoll((va.v1.RepoPollRequest) request,
              (io.grpc.stub.StreamObserver<va.v1.RepoPollReply>) responseObserver);
          break;
        case METHODID_REPO_LIST:
          serviceImpl.repoList((va.v1.RepoListRequest) request,
              (io.grpc.stub.StreamObserver<va.v1.RepoListReply>) responseObserver);
          break;
        case METHODID_REPO_GET_CONFIG:
          serviceImpl.repoGetConfig((va.v1.RepoGetConfigRequest) request,
              (io.grpc.stub.StreamObserver<va.v1.RepoGetConfigReply>) responseObserver);
          break;
        case METHODID_REPO_SAVE_CONFIG:
          serviceImpl.repoSaveConfig((va.v1.RepoSaveConfigRequest) request,
              (io.grpc.stub.StreamObserver<va.v1.RepoSaveConfigReply>) responseObserver);
          break;
        case METHODID_REPO_PUT_FILE:
          serviceImpl.repoPutFile((va.v1.RepoPutFileRequest) request,
              (io.grpc.stub.StreamObserver<va.v1.RepoPutFileReply>) responseObserver);
          break;
        case METHODID_REPO_CONVERT_UPLOAD:
          serviceImpl.repoConvertUpload((va.v1.RepoConvertUploadRequest) request,
              (io.grpc.stub.StreamObserver<va.v1.RepoConvertUploadReply>) responseObserver);
          break;
        case METHODID_REPO_CONVERT_STREAM:
          serviceImpl.repoConvertStream((va.v1.RepoConvertStreamRequest) request,
              (io.grpc.stub.StreamObserver<va.v1.RepoConvertEvent>) responseObserver);
          break;
        case METHODID_REPO_CONVERT_CANCEL:
          serviceImpl.repoConvertCancel((va.v1.RepoConvertCancelRequest) request,
              (io.grpc.stub.StreamObserver<va.v1.RepoConvertCancelReply>) responseObserver);
          break;
        case METHODID_REPO_REMOVE_MODEL:
          serviceImpl.repoRemoveModel((va.v1.RepoRemoveModelRequest) request,
              (io.grpc.stub.StreamObserver<va.v1.RepoRemoveModelReply>) responseObserver);
          break;
        default:
          throw new AssertionError();
      }
    }

    @java.lang.Override
    @java.lang.SuppressWarnings("unchecked")
    public io.grpc.stub.StreamObserver<Req> invoke(
        io.grpc.stub.StreamObserver<Resp> responseObserver) {
      switch (methodId) {
        default:
          throw new AssertionError();
      }
    }
  }

  public static final io.grpc.ServerServiceDefinition bindService(AsyncService service) {
    return io.grpc.ServerServiceDefinition.builder(getServiceDescriptor())
        .addMethod(
          getApplyPipelineMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              va.v1.ApplyPipelineRequest,
              va.v1.ApplyPipelineReply>(
                service, METHODID_APPLY_PIPELINE)))
        .addMethod(
          getApplyPipelinesMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              va.v1.ApplyPipelinesRequest,
              va.v1.ApplyPipelinesReply>(
                service, METHODID_APPLY_PIPELINES)))
        .addMethod(
          getRemovePipelineMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              va.v1.RemovePipelineRequest,
              va.v1.RemovePipelineReply>(
                service, METHODID_REMOVE_PIPELINE)))
        .addMethod(
          getHotSwapModelMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              va.v1.HotSwapModelRequest,
              va.v1.HotSwapModelReply>(
                service, METHODID_HOT_SWAP_MODEL)))
        .addMethod(
          getDrainMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              va.v1.DrainRequest,
              va.v1.DrainReply>(
                service, METHODID_DRAIN)))
        .addMethod(
          getGetStatusMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              va.v1.GetStatusRequest,
              va.v1.GetStatusReply>(
                service, METHODID_GET_STATUS)))
        .addMethod(
          getSubscribePipelineMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              va.v1.SubscribePipelineRequest,
              va.v1.SubscribePipelineReply>(
                service, METHODID_SUBSCRIBE_PIPELINE)))
        .addMethod(
          getUnsubscribePipelineMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              va.v1.UnsubscribePipelineRequest,
              va.v1.UnsubscribePipelineReply>(
                service, METHODID_UNSUBSCRIBE_PIPELINE)))
        .addMethod(
          getSetEngineMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              va.v1.SetEngineRequest,
              va.v1.SetEngineReply>(
                service, METHODID_SET_ENGINE)))
        .addMethod(
          getQueryRuntimeMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              va.v1.QueryRuntimeRequest,
              va.v1.QueryRuntimeReply>(
                service, METHODID_QUERY_RUNTIME)))
        .addMethod(
          getListPipelinesMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              va.v1.ListPipelinesRequest,
              va.v1.ListPipelinesReply>(
                service, METHODID_LIST_PIPELINES)))
        .addMethod(
          getWatchMethod(),
          io.grpc.stub.ServerCalls.asyncServerStreamingCall(
            new MethodHandlers<
              va.v1.WatchRequest,
              va.v1.PhaseEvent>(
                service, METHODID_WATCH)))
        .addMethod(
          getRepoLoadMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              va.v1.RepoLoadRequest,
              va.v1.RepoLoadReply>(
                service, METHODID_REPO_LOAD)))
        .addMethod(
          getRepoUnloadMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              va.v1.RepoUnloadRequest,
              va.v1.RepoUnloadReply>(
                service, METHODID_REPO_UNLOAD)))
        .addMethod(
          getRepoPollMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              va.v1.RepoPollRequest,
              va.v1.RepoPollReply>(
                service, METHODID_REPO_POLL)))
        .addMethod(
          getRepoListMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              va.v1.RepoListRequest,
              va.v1.RepoListReply>(
                service, METHODID_REPO_LIST)))
        .addMethod(
          getRepoGetConfigMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              va.v1.RepoGetConfigRequest,
              va.v1.RepoGetConfigReply>(
                service, METHODID_REPO_GET_CONFIG)))
        .addMethod(
          getRepoSaveConfigMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              va.v1.RepoSaveConfigRequest,
              va.v1.RepoSaveConfigReply>(
                service, METHODID_REPO_SAVE_CONFIG)))
        .addMethod(
          getRepoPutFileMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              va.v1.RepoPutFileRequest,
              va.v1.RepoPutFileReply>(
                service, METHODID_REPO_PUT_FILE)))
        .addMethod(
          getRepoConvertUploadMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              va.v1.RepoConvertUploadRequest,
              va.v1.RepoConvertUploadReply>(
                service, METHODID_REPO_CONVERT_UPLOAD)))
        .addMethod(
          getRepoConvertStreamMethod(),
          io.grpc.stub.ServerCalls.asyncServerStreamingCall(
            new MethodHandlers<
              va.v1.RepoConvertStreamRequest,
              va.v1.RepoConvertEvent>(
                service, METHODID_REPO_CONVERT_STREAM)))
        .addMethod(
          getRepoConvertCancelMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              va.v1.RepoConvertCancelRequest,
              va.v1.RepoConvertCancelReply>(
                service, METHODID_REPO_CONVERT_CANCEL)))
        .addMethod(
          getRepoRemoveModelMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              va.v1.RepoRemoveModelRequest,
              va.v1.RepoRemoveModelReply>(
                service, METHODID_REPO_REMOVE_MODEL)))
        .build();
  }

  private static abstract class AnalyzerControlBaseDescriptorSupplier
      implements io.grpc.protobuf.ProtoFileDescriptorSupplier, io.grpc.protobuf.ProtoServiceDescriptorSupplier {
    AnalyzerControlBaseDescriptorSupplier() {}

    @java.lang.Override
    public com.google.protobuf.Descriptors.FileDescriptor getFileDescriptor() {
      return va.v1.AnalyzerControlOuterClass.getDescriptor();
    }

    @java.lang.Override
    public com.google.protobuf.Descriptors.ServiceDescriptor getServiceDescriptor() {
      return getFileDescriptor().findServiceByName("AnalyzerControl");
    }
  }

  private static final class AnalyzerControlFileDescriptorSupplier
      extends AnalyzerControlBaseDescriptorSupplier {
    AnalyzerControlFileDescriptorSupplier() {}
  }

  private static final class AnalyzerControlMethodDescriptorSupplier
      extends AnalyzerControlBaseDescriptorSupplier
      implements io.grpc.protobuf.ProtoMethodDescriptorSupplier {
    private final java.lang.String methodName;

    AnalyzerControlMethodDescriptorSupplier(java.lang.String methodName) {
      this.methodName = methodName;
    }

    @java.lang.Override
    public com.google.protobuf.Descriptors.MethodDescriptor getMethodDescriptor() {
      return getServiceDescriptor().findMethodByName(methodName);
    }
  }

  private static volatile io.grpc.ServiceDescriptor serviceDescriptor;

  public static io.grpc.ServiceDescriptor getServiceDescriptor() {
    io.grpc.ServiceDescriptor result = serviceDescriptor;
    if (result == null) {
      synchronized (AnalyzerControlGrpc.class) {
        result = serviceDescriptor;
        if (result == null) {
          serviceDescriptor = result = io.grpc.ServiceDescriptor.newBuilder(SERVICE_NAME)
              .setSchemaDescriptor(new AnalyzerControlFileDescriptorSupplier())
              .addMethod(getApplyPipelineMethod())
              .addMethod(getApplyPipelinesMethod())
              .addMethod(getRemovePipelineMethod())
              .addMethod(getHotSwapModelMethod())
              .addMethod(getDrainMethod())
              .addMethod(getGetStatusMethod())
              .addMethod(getSubscribePipelineMethod())
              .addMethod(getUnsubscribePipelineMethod())
              .addMethod(getSetEngineMethod())
              .addMethod(getQueryRuntimeMethod())
              .addMethod(getListPipelinesMethod())
              .addMethod(getWatchMethod())
              .addMethod(getRepoLoadMethod())
              .addMethod(getRepoUnloadMethod())
              .addMethod(getRepoPollMethod())
              .addMethod(getRepoListMethod())
              .addMethod(getRepoGetConfigMethod())
              .addMethod(getRepoSaveConfigMethod())
              .addMethod(getRepoPutFileMethod())
              .addMethod(getRepoConvertUploadMethod())
              .addMethod(getRepoConvertStreamMethod())
              .addMethod(getRepoConvertCancelMethod())
              .addMethod(getRepoRemoveModelMethod())
              .build();
        }
      }
    }
    return result;
  }
}
