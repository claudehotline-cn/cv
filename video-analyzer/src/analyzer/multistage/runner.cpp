#include "analyzer/multistage/runner.hpp"

namespace va { namespace analyzer { namespace multistage {

AnalyzerMultistageAdapter::AnalyzerMultistageAdapter() = default;
AnalyzerMultistageAdapter::~AnalyzerMultistageAdapter() = default;

bool AnalyzerMultistageAdapter::process(const va::core::Frame& in, va::core::Frame& out) {
    Packet p; p.frame = in;
    if (!graph_.run(p, ctx_)) return false;
    out = p.frame;
    return true;
}

} } } // namespace

