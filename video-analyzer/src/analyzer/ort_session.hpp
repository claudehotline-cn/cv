#pragma once

#include "analyzer/interfaces.hpp"

#include <cstddef>
#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace va::analyzer {

class OrtModelSession : public IModelSession {
public:
    struct RuntimeInfo {
        std::string provider {"cpu"};
        bool gpu_active {false};
        bool io_binding_active {false};
        bool device_binding_active {false};
        bool cpu_fallback {false};
    };

#ifdef USE_ONNXRUNTIME
    struct Options {
        std::string provider {"cpu"};
        int device_id {0};
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
        bool stage_device_outputs {false};
        size_t tensor_host_pool_bytes {0};
        size_t tensor_device_pool_bytes {0};
        std::function<void(const RuntimeInfo&)> runtime_callback;
    };

    void setOptions(const Options& options);
#endif

    OrtModelSession();
    ~OrtModelSession() override;

    bool loadModel(const std::string& model_path, bool use_gpu) override;
    bool run(const core::TensorView& input, std::vector<core::TensorView>& outputs) override;

    RuntimeInfo runtimeInfo() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
    bool loaded_ {false};
};

} // namespace va::analyzer
