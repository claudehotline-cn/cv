package com.cv.cp.grpc;

import com.cv.cp.config.AppProperties;
import io.grpc.ManagedChannel;
import io.grpc.ManagedChannelBuilder;
import io.grpc.netty.shaded.io.grpc.netty.GrpcSslContexts;
import io.grpc.netty.shaded.io.grpc.netty.NettyChannelBuilder;
import java.io.File;
import javax.net.ssl.SSLException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class GrpcChannelConfig {

  private static final Logger log = LoggerFactory.getLogger(GrpcChannelConfig.class);

  private final AppProperties properties;

  public GrpcChannelConfig(AppProperties properties) {
    this.properties = properties;
  }

  @Bean(destroyMethod = "shutdownNow")
  public ManagedChannel vaChannel() {
    AppProperties.VaProperties va = properties.getVa();
    return buildChannel(va.getGrpcAddr(), va.getTls());
  }

  @Bean(destroyMethod = "shutdownNow")
  public ManagedChannel vsmChannel() {
    AppProperties.VsmProperties vsm = properties.getVsm();
    return buildChannel(vsm.getGrpcAddr(), vsm.getTls());
  }

  private ManagedChannel buildChannel(String target, AppProperties.TlsProperties tls) {
    if (tls != null && tls.isEnabled()) {
      try {
        NettyChannelBuilder builder = NettyChannelBuilder.forTarget(target)
            // 与 C++ 版 grpc_clients.cpp 保持一致：使用 localhost 作为 SNI/authority，
            // 以匹配开发环境证书中的 SAN=localhost
            .overrideAuthority("localhost");
        builder.sslContext(
            GrpcSslContexts.forClient()
                .trustManager(new File(tls.getRootCertFile()))
                .keyManager(new File(tls.getClientCertFile()), new File(tls.getClientKeyFile()))
                .build());
        return builder.build();
      } catch (SSLException | RuntimeException e) {
        log.warn("Failed to create TLS gRPC channel for {}: {}, falling back to plaintext", target,
            e.toString());
      }
    }
    return ManagedChannelBuilder.forTarget(target).usePlaintext().build();
  }
}
