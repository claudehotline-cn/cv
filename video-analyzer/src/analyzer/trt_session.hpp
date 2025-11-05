#pragma once

#include "analyzer/interfaces.hpp"
#include <memory>
#include <string>
#include <vector>

namespace va::analyzer {

class TensorRTModelSession : public IModelSession {
public:
    struct Options {
        int device_id {0};
        void* user_stream {nullptr}; // cudaStream_t as void*
        bool fp16 {false};
        int workspace_mb {0};
        bool device_output_views {true};
        bool stage_device_outputs {false};
    };

    TensorRTModelSession();
    ~TensorRTModelSession() override;

    // Non-virtual configuration API for factory
    void setOptions(const Options& opt);

    // IModelSession
    bool loadModel(const std::string& model_path, bool use_gpu) override;
    bool run(const core::TensorView& input, std::vector<core::TensorView>& outputs) override;
    ModelRuntimeInfo getRuntimeInfo() const override;
    std::vector<std::string> outputNames() const override;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
    bool loaded_ {false};
};

} // namespace va::analyzer

