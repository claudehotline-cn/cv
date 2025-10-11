#include "control_plane_embedded/adapters/graph_adapter_yaml.hpp"
#include "analyzer/multistage/builder_yaml.hpp"
#include "analyzer/multistage/runner.hpp"
#include "core/logger.hpp"
#include <filesystem>

namespace va { namespace control {

using va::analyzer::multistage::Graph;

namespace {
static std::string resolve_yaml(const PlainPipelineSpec& spec) {
    if (!spec.yaml_path.empty()) return spec.yaml_path;
    if (spec.graph_id.empty()) return {};
    // 尝试在常见目录搜索 config/graphs/<graph_id>.yaml
    std::vector<std::filesystem::path> candidates;
    std::filesystem::path cwd = std::filesystem::current_path();
    candidates.push_back(cwd / "config" / "graphs");
    candidates.push_back(cwd / "video-analyzer" / "config" / "graphs");
    auto cur = cwd;
    for (int i=0;i<4;++i) {
        candidates.push_back(cur / "config" / "graphs");
        candidates.push_back(cur / "video-analyzer" / "config" / "graphs");
        if (cur.has_parent_path()) cur = cur.parent_path(); else break;
    }
    std::error_code ec;
    for (const auto& dir : candidates) {
        auto f1 = dir / (spec.graph_id + ".yaml");
        if (std::filesystem::exists(f1, ec)) return f1.string();
        auto f2 = dir / (spec.graph_id + ".yml");
        if (std::filesystem::exists(f2, ec)) return f2.string();
    }
    return {};
}
}

OpaquePtr GraphAdapterYaml::BuildGraph(const PlainPipelineSpec& spec, std::string* err) {
    auto g = std::make_unique<Graph>();
    std::string file = resolve_yaml(spec);
    if (file.empty()) { if (err) *err = "yaml not found by graph_id/yaml_path"; return {}; }
    if (!va::analyzer::multistage::build_graph_from_yaml(file, *g)) {
        if (err) *err = std::string("build_graph_from_yaml failed: ") + file; return {};
    }
    Graph* raw = g.release();
    return OpaquePtr{raw, [](void* p){ delete reinterpret_cast<Graph*>(p); }};
}

class SimpleExecutor : public IExecutor {
public:
    explicit SimpleExecutor(Graph* g) : g_(g) {}
    bool Start(std::string* /*err*/) override {
        if (!g_) return false;
        // 打开节点（无独立线程，此处仅作为生命周期占位）
        va::analyzer::multistage::NodeContext ctx{};
        opened_ = g_->open_all(ctx);
        return opened_;
    }
    void Stop() override {
        if (!g_) return;
        va::analyzer::multistage::NodeContext ctx{};
        g_->close_all(ctx);
        opened_ = false;
    }
    Status Drain(int /*timeout_sec*/) override { return Status::OK(); }
    Status HotSwapModel(const std::string& /*node*/, const std::string& /*uri*/) override {
        return Status::Internal("HotSwapModel not implemented in SimpleExecutor");
    }
    std::string CollectStatusJson() override { return "{\"phase\":\"Ready\"}"; }
private:
    Graph* g_ {nullptr};
    bool opened_ {false};
};

std::unique_ptr<IExecutor> GraphAdapterYaml::CreateExecutor(void* graph, std::string* /*err*/) {
    auto g = reinterpret_cast<Graph*>(graph);
    if (!g) return {};
    return std::make_unique<SimpleExecutor>(g);
}

} } // namespace
