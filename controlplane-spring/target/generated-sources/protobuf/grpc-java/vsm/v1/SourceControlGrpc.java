package vsm.v1;

import static io.grpc.MethodDescriptor.generateFullMethodName;

/**
 */
@io.grpc.stub.annotations.GrpcGenerated
public final class SourceControlGrpc {

  private SourceControlGrpc() {}

  public static final java.lang.String SERVICE_NAME = "vsm.v1.SourceControl";

  // Static method descriptors that strictly reflect the proto.
  private static volatile io.grpc.MethodDescriptor<vsm.v1.AttachRequest,
      vsm.v1.AttachReply> getAttachMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "Attach",
      requestType = vsm.v1.AttachRequest.class,
      responseType = vsm.v1.AttachReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<vsm.v1.AttachRequest,
      vsm.v1.AttachReply> getAttachMethod() {
    io.grpc.MethodDescriptor<vsm.v1.AttachRequest, vsm.v1.AttachReply> getAttachMethod;
    if ((getAttachMethod = SourceControlGrpc.getAttachMethod) == null) {
      synchronized (SourceControlGrpc.class) {
        if ((getAttachMethod = SourceControlGrpc.getAttachMethod) == null) {
          SourceControlGrpc.getAttachMethod = getAttachMethod =
              io.grpc.MethodDescriptor.<vsm.v1.AttachRequest, vsm.v1.AttachReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "Attach"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  vsm.v1.AttachRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  vsm.v1.AttachReply.getDefaultInstance()))
              .setSchemaDescriptor(new SourceControlMethodDescriptorSupplier("Attach"))
              .build();
        }
      }
    }
    return getAttachMethod;
  }

  private static volatile io.grpc.MethodDescriptor<vsm.v1.DetachRequest,
      vsm.v1.DetachReply> getDetachMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "Detach",
      requestType = vsm.v1.DetachRequest.class,
      responseType = vsm.v1.DetachReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<vsm.v1.DetachRequest,
      vsm.v1.DetachReply> getDetachMethod() {
    io.grpc.MethodDescriptor<vsm.v1.DetachRequest, vsm.v1.DetachReply> getDetachMethod;
    if ((getDetachMethod = SourceControlGrpc.getDetachMethod) == null) {
      synchronized (SourceControlGrpc.class) {
        if ((getDetachMethod = SourceControlGrpc.getDetachMethod) == null) {
          SourceControlGrpc.getDetachMethod = getDetachMethod =
              io.grpc.MethodDescriptor.<vsm.v1.DetachRequest, vsm.v1.DetachReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "Detach"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  vsm.v1.DetachRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  vsm.v1.DetachReply.getDefaultInstance()))
              .setSchemaDescriptor(new SourceControlMethodDescriptorSupplier("Detach"))
              .build();
        }
      }
    }
    return getDetachMethod;
  }

  private static volatile io.grpc.MethodDescriptor<vsm.v1.GetHealthRequest,
      vsm.v1.GetHealthReply> getGetHealthMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "GetHealth",
      requestType = vsm.v1.GetHealthRequest.class,
      responseType = vsm.v1.GetHealthReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<vsm.v1.GetHealthRequest,
      vsm.v1.GetHealthReply> getGetHealthMethod() {
    io.grpc.MethodDescriptor<vsm.v1.GetHealthRequest, vsm.v1.GetHealthReply> getGetHealthMethod;
    if ((getGetHealthMethod = SourceControlGrpc.getGetHealthMethod) == null) {
      synchronized (SourceControlGrpc.class) {
        if ((getGetHealthMethod = SourceControlGrpc.getGetHealthMethod) == null) {
          SourceControlGrpc.getGetHealthMethod = getGetHealthMethod =
              io.grpc.MethodDescriptor.<vsm.v1.GetHealthRequest, vsm.v1.GetHealthReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "GetHealth"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  vsm.v1.GetHealthRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  vsm.v1.GetHealthReply.getDefaultInstance()))
              .setSchemaDescriptor(new SourceControlMethodDescriptorSupplier("GetHealth"))
              .build();
        }
      }
    }
    return getGetHealthMethod;
  }

  private static volatile io.grpc.MethodDescriptor<vsm.v1.WatchStateRequest,
      vsm.v1.WatchStateReply> getWatchStateMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "WatchState",
      requestType = vsm.v1.WatchStateRequest.class,
      responseType = vsm.v1.WatchStateReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.SERVER_STREAMING)
  public static io.grpc.MethodDescriptor<vsm.v1.WatchStateRequest,
      vsm.v1.WatchStateReply> getWatchStateMethod() {
    io.grpc.MethodDescriptor<vsm.v1.WatchStateRequest, vsm.v1.WatchStateReply> getWatchStateMethod;
    if ((getWatchStateMethod = SourceControlGrpc.getWatchStateMethod) == null) {
      synchronized (SourceControlGrpc.class) {
        if ((getWatchStateMethod = SourceControlGrpc.getWatchStateMethod) == null) {
          SourceControlGrpc.getWatchStateMethod = getWatchStateMethod =
              io.grpc.MethodDescriptor.<vsm.v1.WatchStateRequest, vsm.v1.WatchStateReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.SERVER_STREAMING)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "WatchState"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  vsm.v1.WatchStateRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  vsm.v1.WatchStateReply.getDefaultInstance()))
              .setSchemaDescriptor(new SourceControlMethodDescriptorSupplier("WatchState"))
              .build();
        }
      }
    }
    return getWatchStateMethod;
  }

  private static volatile io.grpc.MethodDescriptor<vsm.v1.UpdateRequest,
      vsm.v1.UpdateReply> getUpdateMethod;

  @io.grpc.stub.annotations.RpcMethod(
      fullMethodName = SERVICE_NAME + '/' + "Update",
      requestType = vsm.v1.UpdateRequest.class,
      responseType = vsm.v1.UpdateReply.class,
      methodType = io.grpc.MethodDescriptor.MethodType.UNARY)
  public static io.grpc.MethodDescriptor<vsm.v1.UpdateRequest,
      vsm.v1.UpdateReply> getUpdateMethod() {
    io.grpc.MethodDescriptor<vsm.v1.UpdateRequest, vsm.v1.UpdateReply> getUpdateMethod;
    if ((getUpdateMethod = SourceControlGrpc.getUpdateMethod) == null) {
      synchronized (SourceControlGrpc.class) {
        if ((getUpdateMethod = SourceControlGrpc.getUpdateMethod) == null) {
          SourceControlGrpc.getUpdateMethod = getUpdateMethod =
              io.grpc.MethodDescriptor.<vsm.v1.UpdateRequest, vsm.v1.UpdateReply>newBuilder()
              .setType(io.grpc.MethodDescriptor.MethodType.UNARY)
              .setFullMethodName(generateFullMethodName(SERVICE_NAME, "Update"))
              .setSampledToLocalTracing(true)
              .setRequestMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  vsm.v1.UpdateRequest.getDefaultInstance()))
              .setResponseMarshaller(io.grpc.protobuf.ProtoUtils.marshaller(
                  vsm.v1.UpdateReply.getDefaultInstance()))
              .setSchemaDescriptor(new SourceControlMethodDescriptorSupplier("Update"))
              .build();
        }
      }
    }
    return getUpdateMethod;
  }

  /**
   * Creates a new async stub that supports all call types for the service
   */
  public static SourceControlStub newStub(io.grpc.Channel channel) {
    io.grpc.stub.AbstractStub.StubFactory<SourceControlStub> factory =
      new io.grpc.stub.AbstractStub.StubFactory<SourceControlStub>() {
        @java.lang.Override
        public SourceControlStub newStub(io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
          return new SourceControlStub(channel, callOptions);
        }
      };
    return SourceControlStub.newStub(factory, channel);
  }

  /**
   * Creates a new blocking-style stub that supports all types of calls on the service
   */
  public static SourceControlBlockingV2Stub newBlockingV2Stub(
      io.grpc.Channel channel) {
    io.grpc.stub.AbstractStub.StubFactory<SourceControlBlockingV2Stub> factory =
      new io.grpc.stub.AbstractStub.StubFactory<SourceControlBlockingV2Stub>() {
        @java.lang.Override
        public SourceControlBlockingV2Stub newStub(io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
          return new SourceControlBlockingV2Stub(channel, callOptions);
        }
      };
    return SourceControlBlockingV2Stub.newStub(factory, channel);
  }

  /**
   * Creates a new blocking-style stub that supports unary and streaming output calls on the service
   */
  public static SourceControlBlockingStub newBlockingStub(
      io.grpc.Channel channel) {
    io.grpc.stub.AbstractStub.StubFactory<SourceControlBlockingStub> factory =
      new io.grpc.stub.AbstractStub.StubFactory<SourceControlBlockingStub>() {
        @java.lang.Override
        public SourceControlBlockingStub newStub(io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
          return new SourceControlBlockingStub(channel, callOptions);
        }
      };
    return SourceControlBlockingStub.newStub(factory, channel);
  }

  /**
   * Creates a new ListenableFuture-style stub that supports unary calls on the service
   */
  public static SourceControlFutureStub newFutureStub(
      io.grpc.Channel channel) {
    io.grpc.stub.AbstractStub.StubFactory<SourceControlFutureStub> factory =
      new io.grpc.stub.AbstractStub.StubFactory<SourceControlFutureStub>() {
        @java.lang.Override
        public SourceControlFutureStub newStub(io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
          return new SourceControlFutureStub(channel, callOptions);
        }
      };
    return SourceControlFutureStub.newStub(factory, channel);
  }

  /**
   */
  public interface AsyncService {

    /**
     */
    default void attach(vsm.v1.AttachRequest request,
        io.grpc.stub.StreamObserver<vsm.v1.AttachReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getAttachMethod(), responseObserver);
    }

    /**
     */
    default void detach(vsm.v1.DetachRequest request,
        io.grpc.stub.StreamObserver<vsm.v1.DetachReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getDetachMethod(), responseObserver);
    }

    /**
     */
    default void getHealth(vsm.v1.GetHealthRequest request,
        io.grpc.stub.StreamObserver<vsm.v1.GetHealthReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getGetHealthMethod(), responseObserver);
    }

    /**
     * <pre>
     * Plan B: stream current sources snapshot periodically for instant reaction
     * </pre>
     */
    default void watchState(vsm.v1.WatchStateRequest request,
        io.grpc.stub.StreamObserver<vsm.v1.WatchStateReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getWatchStateMethod(), responseObserver);
    }

    /**
     */
    default void update(vsm.v1.UpdateRequest request,
        io.grpc.stub.StreamObserver<vsm.v1.UpdateReply> responseObserver) {
      io.grpc.stub.ServerCalls.asyncUnimplementedUnaryCall(getUpdateMethod(), responseObserver);
    }
  }

  /**
   * Base class for the server implementation of the service SourceControl.
   */
  public static abstract class SourceControlImplBase
      implements io.grpc.BindableService, AsyncService {

    @java.lang.Override public final io.grpc.ServerServiceDefinition bindService() {
      return SourceControlGrpc.bindService(this);
    }
  }

  /**
   * A stub to allow clients to do asynchronous rpc calls to service SourceControl.
   */
  public static final class SourceControlStub
      extends io.grpc.stub.AbstractAsyncStub<SourceControlStub> {
    private SourceControlStub(
        io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
      super(channel, callOptions);
    }

    @java.lang.Override
    protected SourceControlStub build(
        io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
      return new SourceControlStub(channel, callOptions);
    }

    /**
     */
    public void attach(vsm.v1.AttachRequest request,
        io.grpc.stub.StreamObserver<vsm.v1.AttachReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getAttachMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     */
    public void detach(vsm.v1.DetachRequest request,
        io.grpc.stub.StreamObserver<vsm.v1.DetachReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getDetachMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     */
    public void getHealth(vsm.v1.GetHealthRequest request,
        io.grpc.stub.StreamObserver<vsm.v1.GetHealthReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getGetHealthMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     * <pre>
     * Plan B: stream current sources snapshot periodically for instant reaction
     * </pre>
     */
    public void watchState(vsm.v1.WatchStateRequest request,
        io.grpc.stub.StreamObserver<vsm.v1.WatchStateReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncServerStreamingCall(
          getChannel().newCall(getWatchStateMethod(), getCallOptions()), request, responseObserver);
    }

    /**
     */
    public void update(vsm.v1.UpdateRequest request,
        io.grpc.stub.StreamObserver<vsm.v1.UpdateReply> responseObserver) {
      io.grpc.stub.ClientCalls.asyncUnaryCall(
          getChannel().newCall(getUpdateMethod(), getCallOptions()), request, responseObserver);
    }
  }

  /**
   * A stub to allow clients to do synchronous rpc calls to service SourceControl.
   */
  public static final class SourceControlBlockingV2Stub
      extends io.grpc.stub.AbstractBlockingStub<SourceControlBlockingV2Stub> {
    private SourceControlBlockingV2Stub(
        io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
      super(channel, callOptions);
    }

    @java.lang.Override
    protected SourceControlBlockingV2Stub build(
        io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
      return new SourceControlBlockingV2Stub(channel, callOptions);
    }

    /**
     */
    public vsm.v1.AttachReply attach(vsm.v1.AttachRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getAttachMethod(), getCallOptions(), request);
    }

    /**
     */
    public vsm.v1.DetachReply detach(vsm.v1.DetachRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getDetachMethod(), getCallOptions(), request);
    }

    /**
     */
    public vsm.v1.GetHealthReply getHealth(vsm.v1.GetHealthRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getGetHealthMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * Plan B: stream current sources snapshot periodically for instant reaction
     * </pre>
     */
    @io.grpc.ExperimentalApi("https://github.com/grpc/grpc-java/issues/10918")
    public io.grpc.stub.BlockingClientCall<?, vsm.v1.WatchStateReply>
        watchState(vsm.v1.WatchStateRequest request) {
      return io.grpc.stub.ClientCalls.blockingV2ServerStreamingCall(
          getChannel(), getWatchStateMethod(), getCallOptions(), request);
    }

    /**
     */
    public vsm.v1.UpdateReply update(vsm.v1.UpdateRequest request) throws io.grpc.StatusException {
      return io.grpc.stub.ClientCalls.blockingV2UnaryCall(
          getChannel(), getUpdateMethod(), getCallOptions(), request);
    }
  }

  /**
   * A stub to allow clients to do limited synchronous rpc calls to service SourceControl.
   */
  public static final class SourceControlBlockingStub
      extends io.grpc.stub.AbstractBlockingStub<SourceControlBlockingStub> {
    private SourceControlBlockingStub(
        io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
      super(channel, callOptions);
    }

    @java.lang.Override
    protected SourceControlBlockingStub build(
        io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
      return new SourceControlBlockingStub(channel, callOptions);
    }

    /**
     */
    public vsm.v1.AttachReply attach(vsm.v1.AttachRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getAttachMethod(), getCallOptions(), request);
    }

    /**
     */
    public vsm.v1.DetachReply detach(vsm.v1.DetachRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getDetachMethod(), getCallOptions(), request);
    }

    /**
     */
    public vsm.v1.GetHealthReply getHealth(vsm.v1.GetHealthRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getGetHealthMethod(), getCallOptions(), request);
    }

    /**
     * <pre>
     * Plan B: stream current sources snapshot periodically for instant reaction
     * </pre>
     */
    public java.util.Iterator<vsm.v1.WatchStateReply> watchState(
        vsm.v1.WatchStateRequest request) {
      return io.grpc.stub.ClientCalls.blockingServerStreamingCall(
          getChannel(), getWatchStateMethod(), getCallOptions(), request);
    }

    /**
     */
    public vsm.v1.UpdateReply update(vsm.v1.UpdateRequest request) {
      return io.grpc.stub.ClientCalls.blockingUnaryCall(
          getChannel(), getUpdateMethod(), getCallOptions(), request);
    }
  }

  /**
   * A stub to allow clients to do ListenableFuture-style rpc calls to service SourceControl.
   */
  public static final class SourceControlFutureStub
      extends io.grpc.stub.AbstractFutureStub<SourceControlFutureStub> {
    private SourceControlFutureStub(
        io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
      super(channel, callOptions);
    }

    @java.lang.Override
    protected SourceControlFutureStub build(
        io.grpc.Channel channel, io.grpc.CallOptions callOptions) {
      return new SourceControlFutureStub(channel, callOptions);
    }

    /**
     */
    public com.google.common.util.concurrent.ListenableFuture<vsm.v1.AttachReply> attach(
        vsm.v1.AttachRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getAttachMethod(), getCallOptions()), request);
    }

    /**
     */
    public com.google.common.util.concurrent.ListenableFuture<vsm.v1.DetachReply> detach(
        vsm.v1.DetachRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getDetachMethod(), getCallOptions()), request);
    }

    /**
     */
    public com.google.common.util.concurrent.ListenableFuture<vsm.v1.GetHealthReply> getHealth(
        vsm.v1.GetHealthRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getGetHealthMethod(), getCallOptions()), request);
    }

    /**
     */
    public com.google.common.util.concurrent.ListenableFuture<vsm.v1.UpdateReply> update(
        vsm.v1.UpdateRequest request) {
      return io.grpc.stub.ClientCalls.futureUnaryCall(
          getChannel().newCall(getUpdateMethod(), getCallOptions()), request);
    }
  }

  private static final int METHODID_ATTACH = 0;
  private static final int METHODID_DETACH = 1;
  private static final int METHODID_GET_HEALTH = 2;
  private static final int METHODID_WATCH_STATE = 3;
  private static final int METHODID_UPDATE = 4;

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
        case METHODID_ATTACH:
          serviceImpl.attach((vsm.v1.AttachRequest) request,
              (io.grpc.stub.StreamObserver<vsm.v1.AttachReply>) responseObserver);
          break;
        case METHODID_DETACH:
          serviceImpl.detach((vsm.v1.DetachRequest) request,
              (io.grpc.stub.StreamObserver<vsm.v1.DetachReply>) responseObserver);
          break;
        case METHODID_GET_HEALTH:
          serviceImpl.getHealth((vsm.v1.GetHealthRequest) request,
              (io.grpc.stub.StreamObserver<vsm.v1.GetHealthReply>) responseObserver);
          break;
        case METHODID_WATCH_STATE:
          serviceImpl.watchState((vsm.v1.WatchStateRequest) request,
              (io.grpc.stub.StreamObserver<vsm.v1.WatchStateReply>) responseObserver);
          break;
        case METHODID_UPDATE:
          serviceImpl.update((vsm.v1.UpdateRequest) request,
              (io.grpc.stub.StreamObserver<vsm.v1.UpdateReply>) responseObserver);
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
          getAttachMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              vsm.v1.AttachRequest,
              vsm.v1.AttachReply>(
                service, METHODID_ATTACH)))
        .addMethod(
          getDetachMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              vsm.v1.DetachRequest,
              vsm.v1.DetachReply>(
                service, METHODID_DETACH)))
        .addMethod(
          getGetHealthMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              vsm.v1.GetHealthRequest,
              vsm.v1.GetHealthReply>(
                service, METHODID_GET_HEALTH)))
        .addMethod(
          getWatchStateMethod(),
          io.grpc.stub.ServerCalls.asyncServerStreamingCall(
            new MethodHandlers<
              vsm.v1.WatchStateRequest,
              vsm.v1.WatchStateReply>(
                service, METHODID_WATCH_STATE)))
        .addMethod(
          getUpdateMethod(),
          io.grpc.stub.ServerCalls.asyncUnaryCall(
            new MethodHandlers<
              vsm.v1.UpdateRequest,
              vsm.v1.UpdateReply>(
                service, METHODID_UPDATE)))
        .build();
  }

  private static abstract class SourceControlBaseDescriptorSupplier
      implements io.grpc.protobuf.ProtoFileDescriptorSupplier, io.grpc.protobuf.ProtoServiceDescriptorSupplier {
    SourceControlBaseDescriptorSupplier() {}

    @java.lang.Override
    public com.google.protobuf.Descriptors.FileDescriptor getFileDescriptor() {
      return vsm.v1.SourceControlOuterClass.getDescriptor();
    }

    @java.lang.Override
    public com.google.protobuf.Descriptors.ServiceDescriptor getServiceDescriptor() {
      return getFileDescriptor().findServiceByName("SourceControl");
    }
  }

  private static final class SourceControlFileDescriptorSupplier
      extends SourceControlBaseDescriptorSupplier {
    SourceControlFileDescriptorSupplier() {}
  }

  private static final class SourceControlMethodDescriptorSupplier
      extends SourceControlBaseDescriptorSupplier
      implements io.grpc.protobuf.ProtoMethodDescriptorSupplier {
    private final java.lang.String methodName;

    SourceControlMethodDescriptorSupplier(java.lang.String methodName) {
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
      synchronized (SourceControlGrpc.class) {
        result = serviceDescriptor;
        if (result == null) {
          serviceDescriptor = result = io.grpc.ServiceDescriptor.newBuilder(SERVICE_NAME)
              .setSchemaDescriptor(new SourceControlFileDescriptorSupplier())
              .addMethod(getAttachMethod())
              .addMethod(getDetachMethod())
              .addMethod(getGetHealthMethod())
              .addMethod(getWatchStateMethod())
              .addMethod(getUpdateMethod())
              .build();
        }
      }
    }
    return result;
  }
}
