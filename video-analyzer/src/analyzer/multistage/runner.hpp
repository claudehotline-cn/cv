#pragma once

#include "analyzer/multistage/graph.hpp"
#include "analyzer/analyzer.hpp" // base for factory type compatibility

namespace va { namespace analyzer { namespace multistage {

// Adapter that satisfies factories signature (inherits Analyzer) but routes to Graph
class AnalyzerMultistageAdapter : public va::analyzer::Analyzer {
public:
    AnalyzerMultistageAdapter();
    ~AnalyzerMultistageAdapter() override;

    bool process(const va::core::Frame& in, va::core::Frame& out) override;

    Graph& graph() { return graph_; }
    NodeContext& context() { return ctx_; }
private:
    Graph graph_;
    NodeContext ctx_{};
};

} } } // namespace

