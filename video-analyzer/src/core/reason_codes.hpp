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
// Extended app errors mapping (to降低unknown占比)
static constexpr const char* kAppNotInitialized   = "app_not_initialized";
static constexpr const char* kProfileNotFound     = "profile_not_found";
static constexpr const char* kModelNotFound       = "model_not_found";
static constexpr const char* kNoModelResolved     = "no_model_resolved";
static constexpr const char* kPipelineInitFailed  = "pipeline_init_failed";
static constexpr const char* kPipelineInitModel   = "pipeline_init_model_failed";
static constexpr const char* kSwitchSourceFailed  = "switch_source_failed";
static constexpr const char* kSwitchModelFailed   = "switch_model_failed";
static constexpr const char* kSwitchTaskFailed    = "switch_task_failed";
static constexpr const char* kUpdateParamsFailed  = "update_params_failed";
static constexpr const char* kSetEngineFailed     = "set_engine_failed";
}
