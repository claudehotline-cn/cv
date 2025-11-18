#pragma once

#include "analyzer/multistage/interfaces.hpp"
#include "core/gpu_buffer_pool.hpp"

namespace va { namespace analyzer { namespace multistage {

class NodeNmsYolo : public INode {
public:
    explicit NodeNmsYolo(const std::unordered_map<std::string,std::string>& cfg);
    bool process(Packet& p, NodeContext& ctx) override;
    std::vector<std::string> inputs() const override { return {in_key_}; }
    std::vector<std::string> outputs() const override { return {"rois:det"}; }
    void close(NodeContext& ctx) override;
private:
    std::string in_key_ {"tensor:det_raw"};
    float conf_ {0.25f};
    float iou_ {0.45f};
    bool prefer_cuda_ {false};
    bool emit_gpu_rois_ {false};
    // GPU ROI 缓冲的简单生命周期管理：每帧复用/归还，避免显存持续增长
    va::core::GpuBufferPool* gpu_pool_ {nullptr};
    va::core::GpuBufferPool::Memory gpu_boxes_mem_;
};

} } } // namespace
