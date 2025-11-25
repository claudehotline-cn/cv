package com.cv.cp.config;

import java.util.List;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "cp")
public class AppProperties {

  private VaProperties va;
  private VsmProperties vsm;
  private RestreamProperties restream;
  private SfuProperties sfu;
  private SecurityProperties security;
  private DbProperties db;

  public VaProperties getVa() {
    return va;
  }

  public void setVa(VaProperties va) {
    this.va = va;
  }

  public VsmProperties getVsm() {
    return vsm;
  }

  public void setVsm(VsmProperties vsm) {
    this.vsm = vsm;
  }

  public RestreamProperties getRestream() {
    return restream;
  }

  public void setRestream(RestreamProperties restream) {
    this.restream = restream;
  }

  public SfuProperties getSfu() {
    return sfu;
  }

  public void setSfu(SfuProperties sfu) {
    this.sfu = sfu;
  }

  public SecurityProperties getSecurity() {
    return security;
  }

  public void setSecurity(SecurityProperties security) {
    this.security = security;
  }

  public DbProperties getDb() {
    return db;
  }

  public void setDb(DbProperties db) {
    this.db = db;
  }

  public static class VaProperties {
    private String grpcAddr;
    private int timeoutMs;
    private int retries;
    private TlsProperties tls;

    public String getGrpcAddr() {
      return grpcAddr;
    }

    public void setGrpcAddr(String grpcAddr) {
      this.grpcAddr = grpcAddr;
    }

    public int getTimeoutMs() {
      return timeoutMs;
    }

    public void setTimeoutMs(int timeoutMs) {
      this.timeoutMs = timeoutMs;
    }

    public int getRetries() {
      return retries;
    }

    public void setRetries(int retries) {
      this.retries = retries;
    }

    public TlsProperties getTls() {
      return tls;
    }

    public void setTls(TlsProperties tls) {
      this.tls = tls;
    }
  }

  public static class VsmProperties {
    private String grpcAddr;
    private int retries;
    private TlsProperties tls;

    public String getGrpcAddr() {
      return grpcAddr;
    }

    public void setGrpcAddr(String grpcAddr) {
      this.grpcAddr = grpcAddr;
    }

    public int getRetries() {
      return retries;
    }

    public void setRetries(int retries) {
      this.retries = retries;
    }

    public TlsProperties getTls() {
      return tls;
    }

    public void setTls(TlsProperties tls) {
      this.tls = tls;
    }
  }

  public static class TlsProperties {
    private boolean enabled;
    private String rootCertFile;
    private String clientCertFile;
    private String clientKeyFile;

    public boolean isEnabled() {
      return enabled;
    }

    public void setEnabled(boolean enabled) {
      this.enabled = enabled;
    }

    public String getRootCertFile() {
      return rootCertFile;
    }

    public void setRootCertFile(String rootCertFile) {
      this.rootCertFile = rootCertFile;
    }

    public String getClientCertFile() {
      return clientCertFile;
    }

    public void setClientCertFile(String clientCertFile) {
      this.clientCertFile = clientCertFile;
    }

    public String getClientKeyFile() {
      return clientKeyFile;
    }

    public void setClientKeyFile(String clientKeyFile) {
      this.clientKeyFile = clientKeyFile;
    }
  }

  public static class RestreamProperties {
    private String rtspBase;

    public String getRtspBase() {
      return rtspBase;
    }

    public void setRtspBase(String rtspBase) {
      this.rtspBase = rtspBase;
    }
  }

  public static class SfuProperties {
    private String whepBase;
    private String defaultVariant;
    private String pausePolicy;

    public String getWhepBase() {
      return whepBase;
    }

    public void setWhepBase(String whepBase) {
      this.whepBase = whepBase;
    }

    public String getDefaultVariant() {
      return defaultVariant;
    }

    public void setDefaultVariant(String defaultVariant) {
      this.defaultVariant = defaultVariant;
    }

    public String getPausePolicy() {
      return pausePolicy;
    }

    public void setPausePolicy(String pausePolicy) {
      this.pausePolicy = pausePolicy;
    }
  }

  public static class SecurityProperties {
    private CorsProperties cors;
    private AuthProperties auth;
    private RateLimitProperties rateLimit;

    public CorsProperties getCors() {
      return cors;
    }

    public void setCors(CorsProperties cors) {
      this.cors = cors;
    }

    public AuthProperties getAuth() {
      return auth;
    }

    public void setAuth(AuthProperties auth) {
      this.auth = auth;
    }

    public RateLimitProperties getRateLimit() {
      return rateLimit;
    }

    public void setRateLimit(RateLimitProperties rateLimit) {
      this.rateLimit = rateLimit;
    }
  }

  public static class CorsProperties {
    private List<String> allowedOrigins;

    public List<String> getAllowedOrigins() {
      return allowedOrigins;
    }

    public void setAllowedOrigins(List<String> allowedOrigins) {
      this.allowedOrigins = allowedOrigins;
    }
  }

  public static class AuthProperties {
    private String bearerToken;

    public String getBearerToken() {
      return bearerToken;
    }

    public void setBearerToken(String bearerToken) {
      this.bearerToken = bearerToken;
    }
  }

  public static class RateLimitProperties {
    private int rps;

    public int getRps() {
      return rps;
    }

    public void setRps(int rps) {
      this.rps = rps;
    }
  }

  public static class DbProperties {
    private String driver;
    private String host;
    private int port;
    private String user;
    private String password;
    private String schema;
    private int timeoutMs;

    public String getDriver() {
      return driver;
    }

    public void setDriver(String driver) {
      this.driver = driver;
    }

    public String getHost() {
      return host;
    }

    public void setHost(String host) {
      this.host = host;
    }

    public int getPort() {
      return port;
    }

    public void setPort(int port) {
      this.port = port;
    }

    public String getUser() {
      return user;
    }

    public void setUser(String user) {
      this.user = user;
    }

    public String getPassword() {
      return password;
    }

    public void setPassword(String password) {
      this.password = password;
    }

    public String getSchema() {
      return schema;
    }

    public void setSchema(String schema) {
      this.schema = schema;
    }

    public int getTimeoutMs() {
      return timeoutMs;
    }

    public void setTimeoutMs(int timeoutMs) {
      this.timeoutMs = timeoutMs;
    }
  }
}

