#pragma once

#include "analyzer/multistage/graph.hpp"
#include "analyzer/analyzer.hpp" // base for factory type compatibility
#include "core/buffer_pool.hpp"
#include "core/gpu_buffer_pool.hpp"

namespace va { namespace analyzer { namespace multistage {

// Adapter that satisfies factories signature (inherits Analyzer) but routes to Graph
class AnalyzerMultistageAdapter : public va::analyzer::Analyzer {
public:
    AnalyzerMultistageAdapter();
    ~AnalyzerMultistageAdapter() override;

    bool process(const va::core::Frame& in, va::core::Frame& out) override;

    Graph& graph() { return graph_; }
    NodeContext& context() { return ctx_; }
    void configurePools(std::size_t host_block_bytes, int host_capacity,
                        std::size_t device_block_bytes, int device_capacity);
private:
    Graph graph_;
    NodeContext ctx_{};
    std::unique_ptr<va::core::HostBufferPool> host_pool_;
    std::unique_ptr<va::core::GpuBufferPool>  gpu_pool_;
};

} } } // namespace
