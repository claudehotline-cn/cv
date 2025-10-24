#pragma once

// Canonical reason code strings for subscription failures/cancellation.
// Keep these consistent across REST/SSE payloads and metrics labels.

namespace va::core::reasons {
static constexpr const char* kOpenRtspTimeout  = "open_rtsp_timeout";
static constexpr const char* kOpenRtspFailed   = "open_rtsp_failed";
static constexpr const char* kLoadModelTimeout = "load_model_timeout";
static constexpr const char* kLoadModelFailed  = "load_model_failed";
static constexpr const char* kSubscribeFailed  = "subscribe_failed";
static constexpr const char* kCancelled        = "cancelled";
static constexpr const char* kUnknown          = "unknown";
}

