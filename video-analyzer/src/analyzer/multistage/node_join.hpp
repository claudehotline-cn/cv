#pragma once

#include "analyzer/multistage/interfaces.hpp"
#include <unordered_map>
#include <vector>

namespace va { namespace analyzer { namespace multistage {

// Concatenate multiple input tensors along a given axis (default axis=1).
// Supports CPU (host) and GPU (device) memcpy-based concatenation for contiguous NCHW layouts.
// Params:
//  - ins: CSV of input tensor keys, e.g., "tensor:a,tensor:b"
//  - out: output tensor key (default "tensor:joined")
//  - axis: int (default 1)
//  - prefer_gpu: int/bool (default 1) if all inputs on_gpu and gpu_pool available
class NodeJoin : public INode {
public:
    explicit NodeJoin(const std::unordered_map<std::string,std::string>& cfg);
    bool process(Packet& p, NodeContext& ctx) override;
    std::vector<std::string> inputs() const override { return ins_; }
    std::vector<std::string> outputs() const override { return {out_key_}; }
private:
    std::vector<std::string> ins_;
    std::string out_key_ {"tensor:joined"};
    int axis_ {1};
    bool prefer_gpu_ {true};
    std::vector<float> host_buffer_;
};

} } } // namespace

