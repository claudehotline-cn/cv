package com.cv.cp.service;

import com.cv.cp.domain.subscription.SubscriptionRecord;
import com.cv.cp.dto.SubscriptionCreateDto;
import java.util.Optional;

public interface SubscriptionService {

  SubscriptionRecord create(SubscriptionCreateDto request);

  Optional<SubscriptionRecord> find(String id);

  void delete(String id);
}
