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
