package com.cv.cp.service.impl;

import com.cv.cp.domain.subscription.SubscriptionRecord;
import com.cv.cp.dto.SubscriptionCreateDto;
import com.cv.cp.grpc.VideoAnalyzerClient;
import com.cv.cp.service.SubscriptionService;
import io.grpc.Status;
import io.grpc.StatusRuntimeException;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Service;

@Service
public class SubscriptionServiceImpl implements SubscriptionService {

  private final Map<String, SubscriptionRecord> records = new ConcurrentHashMap<>();
  private final VideoAnalyzerClient videoAnalyzerClient;

  public SubscriptionServiceImpl(VideoAnalyzerClient videoAnalyzerClient) {
    this.videoAnalyzerClient = videoAnalyzerClient;
  }

  private boolean isFakeWatchEnabled() {
    String v = System.getenv("CP_FAKE_WATCH");
    if (v == null) {
      return false;
    }
    String lower = v.toLowerCase();
    return "1".equals(lower) || "true".equals(lower);
  }

  @Override
  public SubscriptionRecord create(SubscriptionCreateDto request) {
    String subscriptionId;
    if (isFakeWatchEnabled()) {
      subscriptionId = "fake-" + request.getStreamId();
    } else {
      try {
        subscriptionId =
            videoAnalyzerClient.subscribePipeline(
                request.getStreamId(), request.getProfile(), request.getSourceUri(),
                request.getModelId());
      } catch (StatusRuntimeException ex) {
        if (ex.getStatus().getCode() == Status.Code.UNAVAILABLE) {
          subscriptionId = "fake-" + request.getStreamId();
        } else {
          throw ex;
        }
      }
    }
    String etag = "\"" + subscriptionId + "-1\"";
    SubscriptionRecord record =
        new SubscriptionRecord(
            subscriptionId,
            etag,
            request.getStreamId(),
            request.getProfile(),
            request.getSourceUri(),
            request.getModelId());
    records.put(subscriptionId, record);
    return record;
  }

  @Override
  public Optional<SubscriptionRecord> find(String id) {
    return Optional.ofNullable(records.get(id));
  }

  @Override
  public void delete(String id) {
    SubscriptionRecord record = records.remove(id);
    if (record != null && !isFakeWatchEnabled()) {
      try {
        videoAnalyzerClient.unsubscribePipeline(record.getStreamId(), record.getProfile());
      } catch (StatusRuntimeException ex) {
        // swallow downstream errors for delete to keep HTTP semantics idempotent
      }
    }
  }
}
