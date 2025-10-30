#pragma once

#include "analyzer/interfaces.hpp"
#include "core/gpu_buffer_pool.hpp"

namespace va::analyzer {

class LetterboxPreprocessorCUDA : public IPreprocessor {
public:
    LetterboxPreprocessorCUDA(int input_width, int input_height);
    ~LetterboxPreprocessorCUDA() override;

    bool run(const core::Frame& in, core::TensorView& out, core::LetterboxMeta& meta) override;
    // 设置外部统一 CUDA 流（void* 以避免头文件依赖）
    void setStream(void* s) { stream_ = s; }

private:
    bool ensureDeviceCapacity(std::size_t bytes);
    void releaseDevice();
    bool ensureInputCapacity(std::size_t bytes);
    void releaseInput();

    int input_width_;
    int input_height_;

    // Unified GPU buffer pools for output tensor and input staging
    std::unique_ptr<va::core::GpuBufferPool> out_pool_;
    std::unique_ptr<va::core::GpuBufferPool> in_pool_;
    va::core::GpuBufferPool::Memory out_mem_{};
    va::core::GpuBufferPool::Memory in_mem_{};
    void* device_ptr_ {nullptr};
    std::size_t capacity_bytes_ {0};
    void* input_device_ptr_ {nullptr};
    std::size_t input_capacity_bytes_ {0};
    void* stream_ {nullptr};
};

} // namespace va::analyzer
