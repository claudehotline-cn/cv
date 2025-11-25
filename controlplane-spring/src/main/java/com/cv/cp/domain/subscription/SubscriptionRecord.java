package com.cv.cp.domain.subscription;

public class SubscriptionRecord {

  private final String id;
  private final String etag;
  private final String streamId;
  private final String profile;
  private final String sourceUri;
  private final String modelId;

  public SubscriptionRecord(
      String id,
      String etag,
      String streamId,
      String profile,
      String sourceUri,
      String modelId) {
    this.id = id;
    this.etag = etag;
    this.streamId = streamId;
    this.profile = profile;
    this.sourceUri = sourceUri;
    this.modelId = modelId;
  }

  public String getId() {
    return id;
  }

  public String getEtag() {
    return etag;
  }

  public String getStreamId() {
    return streamId;
  }

  public String getProfile() {
    return profile;
  }

  public String getSourceUri() {
    return sourceUri;
  }

  public String getModelId() {
    return modelId;
  }
}

