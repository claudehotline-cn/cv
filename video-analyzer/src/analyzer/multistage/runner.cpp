#include "analyzer/multistage/runner.hpp"

namespace va { namespace analyzer { namespace multistage {

AnalyzerMultistageAdapter::AnalyzerMultistageAdapter() = default;
AnalyzerMultistageAdapter::~AnalyzerMultistageAdapter() {
    // Ensure nodes are closed with the correct context
    graph_.close_all(ctx_);
}

bool AnalyzerMultistageAdapter::process(const va::core::Frame& in, va::core::Frame& out) {
    Packet p; p.frame = in;
    if (!graph_.run(p, ctx_)) return false;
    out = p.frame;
    return true;
}

} } } // namespace
