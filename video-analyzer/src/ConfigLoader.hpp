#pragma once

#include <cstddef>
#include <map>
#include <optional>
#include <string>
#include <vector>

struct ModelConfig;
struct ProfileConfig;
struct InferenceConfig;

struct DetectionModelEntry {
    std::string id;
    std::string task;   // det / seg / pose ...
    std::string family;
    std::string variant;
    std::string type;
    std::string path;
    int input_width {0};
    int input_height {0};
    float conf {0.0f};
    float iou {0.0f};
};

struct ProfileEntry {
    std::string name;
    std::string task; // "det" or "seg"
    std::string model_id;
    std::string model_family;
    std::string model_variant;
    std::string model_path;
    int input_width {0};
    int input_height {0};
    int enc_width {0};
    int enc_height {0};
    int enc_fps {0};
    int enc_bitrate_kbps {0};
    int enc_gop {0};
    int enc_bframes {0};
    bool enc_zero_latency {true};
    std::string enc_preset;
    std::string enc_tune;
    std::string enc_profile;
    std::string enc_codec;
    std::string publish_whip_template;
    std::string publish_whep_template;
};

struct AnalyzerParamsEntry {
    float conf {0.0f};
    float iou {0.0f};
    std::vector<std::string> class_whitelist;
    std::optional<std::string> classes_literal;
};

struct EngineOptions {
    bool use_io_binding {false};
    bool prefer_pinned_memory {true};
    bool allow_cpu_fallback {true};
    bool enable_profiling {false};
    bool tensorrt_fp16 {false};
   bool tensorrt_int8 {false};
   int tensorrt_workspace_mb {0};
    int tensorrt_max_partition_iterations {0};
    int tensorrt_min_subgraph_size {0};
    size_t io_binding_input_bytes {0};
    size_t io_binding_output_bytes {0};
    // Source/encoder toggles (plumb to EngineDescriptor.options)
    bool use_ffmpeg_source {false};
    bool use_nvdec {false};
    bool use_nvenc {false};
    bool device_output_views {false};
    bool stage_device_outputs {false};
    bool use_cuda_nms {false};
    bool render_passthrough {false};
    bool render_cuda {false};
    bool use_cuda_preproc {false};
    std::string warmup_runs; // e.g., "auto" or digits
    int overlay_thickness {0};
    double overlay_alpha {0.0};
    // Multistage options (pass-through to EngineDescriptor.options)
    bool use_multistage {false};
    std::string graph_id;           // load from config/graphs/<graph_id>.yaml if set
    std::string multistage_yaml;    // explicit YAML path override
};

struct AppEngineSpec {
    std::string type; // ort-cpu / ort-cuda / ort-trt
    std::string provider;
    int device {0};
    EngineOptions options;
};

struct ObservabilityConfig {
    std::string log_level {"info"};
    bool console {true};
    std::string file_path;
    int file_max_size_kb {0};
    int file_max_files {0};
    bool pipeline_metrics_enabled {false};
    int pipeline_metrics_interval_ms {5000};
    // Metrics registry + labels
    bool metrics_registry_enabled {true};
    bool metrics_extended_labels {false};
    // Metrics series TTL seconds (per-source shard cleanup); <=0 disables
    int metrics_ttl_seconds {300};
    // Added: logging format and module-level overrides from config file
    // log_format: "text" | "json"
    std::string log_format {"text"};
    // module_levels: e.g., "transport.webrtc:debug,encoder.ffmpeg:info"
    std::string module_levels;
};

struct SubscriptionsConfig {
    int heavy_slots {2};
    int model_slots {2};
    int rtsp_slots {4};
    // 分阶段并发（若未设置则在服务器初始化时回退到 legacy 值）
    int open_rtsp_slots {0};
    int load_model_slots {0};
    int start_pipeline_slots {0};
    std::size_t max_queue {1024};
    int ttl_seconds {900};
    // 回显来源：defaults/config/env（仅用于 /api/system/info 展示，不参与业务）
    std::string source;
};

struct AppConfigPayload {
    AppEngineSpec engine;
    std::string sfu_whip_base;
    std::string sfu_whep_base;
    ObservabilityConfig observability;
    SubscriptionsConfig subscriptions; // 订阅参数（YAML 可配）
    struct QuotasConfig {
        bool enabled { false };
        std::string header_key { "X-API-Key" };
        struct DefaultCfg { int concurrent {3}; int rate_per_min {10}; } def;
        struct GlobalCfg { int concurrent {0}; } global; // 0=disabled
        struct AclCfg { std::vector<std::string> allowed_schemes; std::vector<std::string> allowed_profiles; } acl;
        // Gray release / observe-only
        bool observe_only { false };     // true: 不拦截，仅计数 would_drop
        int enforce_percent { 100 };     // 0..100 采样拦截比例
        std::vector<std::string> exempt_keys; // 白名单 keys，不受配额/ACL 影响
        struct KeyOverride { std::string key; int concurrent {0}; int rate_per_min {0}; int enforce_percent { -1 }; bool observe_only { false }; };
        std::vector<KeyOverride> key_overrides; // 针对指定 key 的覆盖（0=不覆盖）
    } quotas;
    struct DatabasePoolConfig {
        int min {4};
        int max {16};
        int timeout_ms {2000};
    };
    struct DatabaseConfig {
        std::string driver; // e.g., mysql
        std::string host;
        int port {0};
        std::string user;
        std::string password;
        std::string db;
        DatabasePoolConfig pool;
        struct RetentionConfig {
            bool enabled {false};
            std::uint64_t events_seconds {0};
            std::uint64_t logs_seconds {0};
            // How often to run purge (seconds). <=0 disables scheduler even if enabled.
            int interval_seconds {600};
            // Random jitter percentage to avoid thundering herd (0-100)
            int jitter_percent {10};
        } retention;
    } database;
    struct ControlPlaneConfig {
        bool enabled {false};
        std::string grpc_addr; // e.g., 0.0.0.0:9090
        std::string vsm_addr;  // optional: vsm gRPC address for WatchState, e.g., 127.0.0.1:7070
        // WatchState tunables (defaults match env-based values)
        int watch_interval_ms {1500};
        int debounce_ms {300};
        int keepalive_time_ms {20000};
        int keepalive_timeout_ms {10000};
        bool keepalive_permit_without_calls {true};
        int watch_deadline_ms {60000};
        int backoff_start_ms {500};
        int backoff_max_ms {10000};
        double backoff_jitter {0.2};
    } control_plane;
};

class ConfigLoader {
public:
    static std::vector<DetectionModelEntry> loadDetectionModels(const std::string& config_dir);
    static std::vector<ProfileEntry> loadProfiles(const std::string& config_dir);
    static AppConfigPayload loadAppConfig(const std::string& config_dir);
    static std::map<std::string, AnalyzerParamsEntry> loadAnalyzerParams(const std::string& config_dir);
};
