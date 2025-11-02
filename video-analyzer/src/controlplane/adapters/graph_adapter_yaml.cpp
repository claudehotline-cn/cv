#include "controlplane/adapters/graph_adapter_yaml.hpp"
#include "analyzer/multistage/builder_yaml.hpp"
#include "analyzer/multistage/runner.hpp"
#include "analyzer/multistage/registry.hpp"
#include "analyzer/multistage/node_preproc_letterbox.hpp"
#include "analyzer/multistage/node_model.hpp"
#include "analyzer/multistage/node_nms.hpp"
#include "analyzer/multistage/node_overlay.hpp"
#include "analyzer/multistage/node_roi_batch.hpp"
#include "analyzer/multistage/node_roi_batch_cuda.hpp"
#include "analyzer/multistage/node_kpt_decode.hpp"
#include "analyzer/multistage/node_overlay_kpt.hpp"
#include "analyzer/multistage/node_join.hpp"
#include "analyzer/multistage/node_reid_smooth.hpp"
#include "core/logger.hpp"
#include "core/engine_manager.hpp"
#include <filesystem>
#include <fstream>
#include "core/global_metrics.hpp"

namespace va { namespace control {

using va::analyzer::multistage::Graph;

namespace {
static void ensure_ms_nodes_registered() {
    using va::analyzer::multistage::NodeRegistry;
    using va::analyzer::multistage::NodePreprocLetterbox;
    using va::analyzer::multistage::NodeModel;
    using va::analyzer::multistage::NodeNmsYolo;
    using va::analyzer::multistage::NodeOverlay;
    using va::analyzer::multistage::NodeRoiBatch;
    using va::analyzer::multistage::NodeRoiBatchCuda;
    using va::analyzer::multistage::NodeKptDecode;
    using va::analyzer::multistage::NodeOverlayKpt;
    using va::analyzer::multistage::NodeJoin;
    using va::analyzer::multistage::NodeReidSmooth;
    static std::once_flag once;
    std::call_once(once, []{
        MS_REGISTER_NODE("preproc.letterbox", NodePreprocLetterbox);
        MS_REGISTER_NODE("model.ort", NodeModel);
        MS_REGISTER_NODE("post.yolo.nms", NodeNmsYolo);
        MS_REGISTER_NODE("overlay.cuda", NodeOverlay);
        va::analyzer::multistage::NodeRegistry::instance().reg("overlay.cpu", [](const std::unordered_map<std::string,std::string>& cfg){ return std::make_shared<NodeOverlay>(cfg); });
        MS_REGISTER_NODE("roi.batch", NodeRoiBatch);
        MS_REGISTER_NODE("roi.batch.cuda", NodeRoiBatchCuda);
        MS_REGISTER_NODE("post.yolo.kpt", NodeKptDecode);
        MS_REGISTER_NODE("overlay.kpt", NodeOverlayKpt);
        MS_REGISTER_NODE("join", NodeJoin);
        MS_REGISTER_NODE("reid.smooth", NodeReidSmooth);
    });
}
static std::string resolve_yaml(const PlainPipelineSpec& spec) {
    if (!spec.yaml_path.empty()) return spec.yaml_path;
    if (spec.graph_id.empty()) {
        if (!spec.template_id.empty()) {
            std::vector<std::filesystem::path> tdirs;
            std::filesystem::path cwd = std::filesystem::current_path();
            tdirs.push_back(cwd / "config" / "graphs");
            tdirs.push_back(cwd / "video-analyzer" / "config" / "graphs");
            auto cur = cwd;
            for (int i=0;i<4;++i) {
                tdirs.push_back(cur / "config" / "graphs");
                tdirs.push_back(cur / "video-analyzer" / "config" / "graphs");
                if (cur.has_parent_path()) cur = cur.parent_path(); else break;
            }
            std::error_code ec;
            for (const auto& dir : tdirs) {
                auto f1 = dir / (spec.template_id + ".yaml");
                if (std::filesystem::exists(f1, ec)) return f1.string();
                auto f2 = dir / (spec.template_id + ".yml");
                if (std::filesystem::exists(f2, ec)) return f2.string();
            }
        }
        return {};
    }
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
    ensure_ms_nodes_registered();
    auto g = std::make_unique<Graph>();
    std::string file = resolve_yaml(spec);
    if (file.empty()) { if (err) *err = "yaml not found by graph_id/yaml_path"; return {}; }
    overrides_cache_ = spec.overrides;
    std::string expanded_file = file;
    try {
        std::ifstream ifs(file, std::ios::binary);
        std::string content((std::istreambuf_iterator<char>(ifs)), std::istreambuf_iterator<char>());
        expanded_file = file;
    } catch (...) { /* ignore */ }
    auto gptr = g.get();
    va::analyzer::multistage::build_graph_from_yaml_with_overrides(expanded_file, overrides_cache_, *g);
    return OpaquePtr(reinterpret_cast<void*>(g.release()), [](void* p){ delete reinterpret_cast<Graph*>(p); });
}

class SimpleExecutor final : public IExecutor {
public:
    explicit SimpleExecutor(Graph* g, va::core::EngineManager* em, std::unordered_map<std::string,std::string> overrides)
        : g_(g), engine_manager_(em), overrides_(std::move(overrides)) {}
    bool Start(std::string* /*err*/) override {
        try {
            if (!g_) return false;
            va::analyzer::multistage::NodeContext ctx{}; ctx.engine_registry = reinterpret_cast<void*>(engine_manager_);
            bool ok = g_->open_all(ctx);
            opened_ = ok;
            return ok;
        } catch (...) { return false; }
    }
    void Stop() override {
        try { if (g_ && opened_) { va::analyzer::multistage::NodeContext ctx{}; ctx.engine_registry = reinterpret_cast<void*>(engine_manager_); g_->close_all(ctx); } } catch (...) {}
    }
    Status Drain(int /*timeout_sec*/) override {
        try {
            if (!g_) return Status::Internal("no graph");
            return Status::OK();
        } catch (const std::exception& ex) {
            return Status::Internal(std::string("drain exception: ")+ex.what());
        } catch (...) {
            return Status::Internal("drain unknown exception");
        }
    }
    Status HotSwapModel(const std::string& node, const std::string& uri) override {
        try {
            if (!g_) return Status::Internal("no graph");
            if (node.empty() || uri.empty()) return Status::InvalidArgument("missing node/model_uri");
            va::analyzer::multistage::NodeContext ctx{}; ctx.engine_registry = reinterpret_cast<void*>(engine_manager_);
            bool ok = g_->with_node(node, [&](va::analyzer::multistage::NodePtr& n, std::string& type, std::unordered_map<std::string,std::string>& cfg){
                (void)type;
                auto* raw = n.get();
                auto* nm = dynamic_cast<va::analyzer::multistage::NodeModel*>(raw);
                if (!nm) return false;
                bool swapped = nm->hotSwapModel(uri, ctx);
                if (swapped) cfg["model_path"] = uri; // persist in cfg
                return swapped;
            });
            return ok ? Status::OK() : Status::NotFound("pipeline node not found or not model");
        } catch (const std::exception& ex) {
            return Status::Internal(std::string("hotswap exception: ")+ex.what());
        } catch (...) {
            return Status::Internal("hotswap unknown exception");
        }
    }
    std::string CollectStatusJson() override {
        try {
            std::ostringstream o;
            o << "{\"phase\":\"Ready\"}";
            return o.str();
        } catch (...) { return "{\"phase\":\"Ready\"}"; }
    }
private:
    Graph* g_ {nullptr};
    va::core::EngineManager* engine_manager_ {nullptr};
    bool opened_ {false};
    std::unordered_map<std::string,std::string> overrides_;
};

std::unique_ptr<IExecutor> GraphAdapterYaml::CreateExecutor(void* graph, std::string* /*err*/) {
    auto g = reinterpret_cast<Graph*>(graph);
    if (!g) return {};
    return std::make_unique<SimpleExecutor>(g, engine_manager_, overrides_cache_);
}

} } // namespace
