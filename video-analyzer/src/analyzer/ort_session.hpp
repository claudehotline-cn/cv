#pragma once

#include "analyzer/interfaces.hpp"

#include <cstddef>
#include <memory>
#include <string>
#include <vector>

namespace va::analyzer {

class OrtModelSession : public IModelSession {
public:
#ifdef USE_ONNXRUNTIME
    struct Options {
        std::string provider {"cpu"};
        int device_id {0};
        // Optional user-provided CUDA stream (void* to avoid CUDA headers)
        void* user_stream {nullptr};
        bool use_io_binding {false};
        bool prefer_pinned_memory {true};
        bool allow_cpu_fallback {true};
        bool enable_profiling {false};
        bool tensorrt_fp16 {false};
        bool tensorrt_int8 {false};
        int tensorrt_workspace_mb {0};
        int tensorrt_max_partition_iterations {0};
        int tensorrt_min_subgraph_size {0};
        // Optional TensorRT dynamic shape profile hints (pass-through to ORT TRTEP)
        // Format: "input_name:1x3x640x640;other_input:..."
        std::string tensorrt_profile_min_shapes;
        std::string tensorrt_profile_opt_shapes;
        std::string tensorrt_profile_max_shapes;
        // Optional builder knobs
        int tensorrt_builder_optimization_level { -1 }; // -1 = unset
        bool tensorrt_force_sequential_build { false };  // map to trt_force_sequential_engine_build
        int tensorrt_auxiliary_streams { -1 };           // map to trt_auxiliary_streams
        bool tensorrt_detailed_build_log { false };      // map to trt_detailed_build_log
        size_t io_binding_input_bytes {0};
        size_t io_binding_output_bytes {0};
        // stage outputs to host after IoBinding run (safe ownership, optional)
        bool stage_device_outputs {false};
        // optional initial bytes for host pool blocks (0 = dynamic by first output)
        size_t tensor_host_pool_bytes {0};
        // expose IoBinding outputs as device views (no host staging)
        bool device_output_views {false};
        // warmup runs right after model load (0 = disable)
        int warmup_runs {1};
        // RTX EP 暂不实现：忽略相关严格要求（总是回退到常规 tensorrt/cuda/cpu）
        bool require_rtx_when_requested {false};
    };

    void setOptions(const Options& options);
#endif

    struct RuntimeInfo {
        std::string provider {"cpu"};
        bool gpu_active {false};
        bool io_binding_active {false};
        bool device_binding_active {false};
        bool cpu_fallback {false};
    };

    OrtModelSession();
    ~OrtModelSession() override;

    bool loadModel(const std::string& model_path, bool use_gpu) override;
    bool run(const core::TensorView& input, std::vector<core::TensorView>& outputs) override;

    // Backward-compat provider-specific runtime info
    RuntimeInfo runtimeInfo() const;

    // IModelSession introspection
    ModelRuntimeInfo getRuntimeInfo() const override;
    // Returns the model's output tensor names if available (empty otherwise).
    std::vector<std::string> outputNames() const override;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
    bool loaded_ {false};
};

} // namespace va::analyzer
