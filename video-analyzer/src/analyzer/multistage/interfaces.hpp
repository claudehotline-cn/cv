#pragma once

#include <memory>
#include <string>
#include <unordered_map>
#include <vector>
#include <variant>

#include "core/utils.hpp"
#include "core/buffer_pool.hpp"
#include "core/gpu_buffer_pool.hpp"

namespace va { namespace analyzer { namespace multistage {

// Lightweight ROI; reuse core::Box for compatibility
using Roi = va::core::Box;

using Attr = std::variant<int64_t, double, float, std::string>;
using TensorDict = std::unordered_map<std::string, va::core::TensorView>;
using AttrDict   = std::unordered_map<std::string, Attr>;
using RoiDict    = std::unordered_map<std::string, std::vector<Roi>>;

// A packet flowing through nodes per frame
struct Packet {
    va::core::Frame frame;                 // Input/output frame
    va::core::LetterboxMeta letterbox;     // Optional letterbox meta
    TensorDict tensors;                    // Named tensor views
    RoiDict rois;                          // Named ROI lists
    AttrDict attrs;                        // Free-form attributes
};

struct NodeContext {
    void* stream {nullptr};                // cudaStream_t or nullptr (kept as void* to avoid headers)
    va::core::HostBufferPool* host_pool {nullptr};
    va::core::GpuBufferPool*  gpu_pool  {nullptr};
    void* engine_registry {nullptr};       // Optional engine/session registry
    void* logger {nullptr};                // Optional logger
};

class INode {
public:
    virtual ~INode() = default;
    virtual bool open(NodeContext&) { return true; }
    virtual void close(NodeContext&) {}
    virtual bool process(Packet& inout, NodeContext&) = 0;
    virtual std::vector<std::string> inputs() const { return {}; }
    virtual std::vector<std::string> outputs() const { return {}; }
};

using NodePtr = std::shared_ptr<INode>;

} } } // namespace va::analyzer::multistage

