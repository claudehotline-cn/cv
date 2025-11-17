#pragma once

#include "analyzer/multistage/interfaces.hpp"
#include "analyzer/interfaces.hpp" // IModelSession
#include <atomic>

namespace va { namespace analyzer { namespace multistage {

  class NodeModel : public INode {
  public:
    explicit NodeModel(const std::unordered_map<std::string,std::string>& cfg);
    bool open(NodeContext&) override;
    bool process(Packet& p, NodeContext& ctx) override;
    std::vector<std::string> inputs() const override { return {in_key_}; }
    std::vector<std::string> outputs() const override { return out_keys_; }
    // Hot-swap model at runtime (reload session with new model path)
    bool hotSwapModel(const std::string& new_model_path, NodeContext& ctx);
    // Introspection: recent inference failure count (monotonic)
    uint64_t infer_fail_count() const { return infer_fail_count_; }
  private:
    std::string in_key_ {"tensor:det_input"};
    std::vector<std::string> out_keys_ {"tensor:det_raw"};
    std::shared_ptr<va::analyzer::IModelSession> session_;
    std::string model_path_;         // 默认/通用路径（兼容旧配置）
    std::string model_path_trt_;     // 原生 TensorRT 路径（.engine）
    std::string model_path_ort_;     // ORT/ORT-TRT/CUDA 路径（.onnx）
    std::string model_path_triton_;  // Triton 仓库模型名（目录名），如 "yolov12x"
    std::string force_provider_override_; // 可选：按节点覆盖 provider（如仅 reid 节点用 cuda）
    std::string triton_input_override_;    // 可选：按节点覆盖 Triton 输入名（如 "images"/"input"）
    std::string triton_outputs_override_;    // 可选：按节点固定 Triton 输出名列表（如 "output0"）
    std::string triton_gpu_output_override_; // 可选：按节点覆盖 Triton GPU 输出开关（如 "0"/"1"）
    bool roi_seq_batch_ {false};             // 可选：对 ROI batch 模型按 ROI 顺序逐个推理（batch size=1 模型）
    std::vector<float> roi_seq_feat_buf_;    // ROI 顺序推理的聚合特征缓冲（CPU）
    // ROI 顺序推理时在 GPU 上聚合特征的缓冲区（使用 GpuBufferPool 管理生命周期，单块复用）
    va::core::GpuBufferPool::Memory roi_seq_gpu_mem_;
    std::atomic<uint64_t> infer_fail_count_{0};
  };

} } } // namespace
