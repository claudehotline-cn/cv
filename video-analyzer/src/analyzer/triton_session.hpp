#pragma once

#include "analyzer/interfaces.hpp"

#include <memory>
#include <string>
#include <vector>

namespace va::analyzer {

class TritonGrpcModelSession : public IModelSession {
public:
    struct Options {
        std::string url{"localhost:8001"};
        std::string model_name;
        std::string model_version; // empty=latest
        std::string input_name{"images"};
        std::vector<std::string> output_names{"dets"};
        int timeout_ms{2000};
        bool use_cuda_shm{false};
        size_t cuda_shm_bytes{0};
        int device_id{0};
    };

    explicit TritonGrpcModelSession(const Options& opt);
    ~TritonGrpcModelSession() override;

    bool loadModel(const std::string& /*unused*/, bool /*use_gpu*/) override;
    bool run(const core::TensorView& input, std::vector<core::TensorView>& outputs) override;
    ModelRuntimeInfo getRuntimeInfo() const override;
    std::vector<std::string> outputNames() const override { return opt_.output_names; }

private:
    Options opt_;
    bool loaded_{false};
};

} // namespace va::analyzer

