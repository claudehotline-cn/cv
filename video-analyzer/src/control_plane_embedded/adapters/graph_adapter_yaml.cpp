#include "control_plane_embedded/adapters/graph_adapter_yaml.hpp"
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
        // M3: 当未显式提供 graph_id/yaml_path 时，支持按 template_id 解析
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
    // 尝试在常见目录下查找 config/graphs/<graph_id>.yaml
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
    // Placeholder expansion: ${key} resolved from overrides.params.key / params.key / key
    overrides_cache_ = spec.overrides;
    std::string expanded_file = file;
    try {
        // Read YAML
        std::ifstream ifs(file, std::ios::binary);
        std::string content((std::istreambuf_iterator<char>(ifs)), std::istreambuf_iterator<char>());
        if (ifs.good() || !content.empty()) {
            // Find placeholders ${...}
            std::string out; out.reserve(content.size());
            for (size_t i = 0; i < content.size(); ) {
                if (content[i] == '$' && i + 1 < content.size() && content[i+1] == '{') {
                    size_t j = i + 2; // after ${
                    while (j < content.size() && content[j] != '}') ++j;
                    if (j < content.size() && content[j] == '}') {
                        std::string key = content.substr(i+2, j - (i+2));
                        auto lookup = [&](const std::string& k)->std::optional<std::string>{
                            if (auto it = overrides_cache_.find(std::string("overrides.params.") + k); it != overrides_cache_.end()) return it->second;
                            if (auto it = overrides_cache_.find(std::string("params.") + k); it != overrides_cache_.end()) return it->second;
                            if (auto it = overrides_cache_.find(k); it != overrides_cache_.end()) return it->second;
                            return std::nullopt;
                        };
                        auto val = lookup(key);
                        if (val) {
                            // Insert as-is to let YAML parse types (bool/int/float/string via quotes if user supplied)
                            out.append(val->begin(), val->end());
                            i = j + 1;
                            continue;
                        }
                    }
                }
                out.push_back(content[i]);
                ++i;
            }
            if (out != content) {
                // Write to a temp file next to original
                auto tmp = std::filesystem::path(file).filename().string();
                std::string tmpname = (std::filesystem::temp_directory_path() / (tmp + ".expanded.yaml")).string();
                std::ofstream ofs(tmpname, std::ios::binary);
                ofs.write(out.data(), static_cast<std::streamsize>(out.size()));
                ofs.close();
                expanded_file = tmpname;
                VA_LOG_C(::va::core::LogLevel::Info, "control") << "[GraphAdapterYaml] expanded placeholders into temp: " << expanded_file;
            }
        }
    } catch (...) {
        // best-effort: fall back to original file
        expanded_file = file;
    }
    bool ok=false; const bool has_node_ov = std::any_of(overrides_cache_.begin(), overrides_cache_.end(), [](const auto& kv){ return kv.first.rfind("node.",0)==0 || kv.first.rfind("type:",0)==0; }); if (has_node_ov) ok = va::analyzer::multistage::build_graph_from_yaml_with_overrides(expanded_file, overrides_cache_, *g); else ok = va::analyzer::multistage::build_graph_from_yaml(expanded_file, *g); if (!ok) {
        if (err) *err = std::string("build_graph_from_yaml failed: ") + file; return {};
    }
    Graph* raw = g.release();
    return OpaquePtr{raw, [](void* p){ delete reinterpret_cast<Graph*>(p); }};
}

class SimpleExecutor : public IExecutor {
public:
    explicit SimpleExecutor(Graph* g, va::core::EngineManager* em, std::unordered_map<std::string,std::string> overrides = {}) : g_(g), em_(em), overrides_(std::move(overrides)) {}
    bool Start(std::string* /*err*/) override {
        if (!g_) return false;
        // 打开节点（无数据/单线程，此处仅为控制面占位）
        va::analyzer::multistage::NodeContext ctx{};
        ctx.engine_registry = reinterpret_cast<void*>(em_);
        // Apply engine overrides scoped to graph open (per-pipeline)
        va::core::EngineDescriptor saved_desc; bool touched=false;
        if (em_) {
            saved_desc = em_->currentEngine();
            auto desc = saved_desc;
            for (const auto& kv : overrides_) {
                const auto& k = kv.first; const auto& v = kv.second;
                if (k.rfind("engine.options.", 0) == 0) { auto sub = k.substr(std::string("engine.options.").size()); if (!sub.empty()) { desc.options[sub]=v; touched=true; } }
                else if (k == "engine.provider") { desc.provider = v; touched=true; }
                else if (k == "engine.name") { desc.name = v; touched=true; }
                else if (k == "engine.device" || k == "engine.device_index") { try { desc.device_index = std::stoi(v); touched=true; } catch (...) {} }
            }
            if (touched) em_->setEngine(desc);
        }
        opened_ = g_->open_all(ctx);
        if (em_ && touched) { try { em_->setEngine(saved_desc); } catch(...){} }
        return opened_;
    }
    void Stop() override {
        if (!g_) return;
        va::analyzer::multistage::NodeContext ctx{};
        ctx.engine_registry = reinterpret_cast<void*>(em_);
        g_->close_all(ctx);
        opened_ = false;
    }
    Status Drain(int /*timeout_sec*/) override {
        try {
            auto gm_before = va::core::GlobalMetrics::snapshot();
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
            auto gm_after = va::core::GlobalMetrics::snapshot();
            last_blocked_nodes_.clear();
            last_drain_reason_.clear();
            if (gm_after.eagain_retry_count > gm_before.eagain_retry_count) {
                last_blocked_nodes_.push_back("encoder");
                last_drain_reason_ = "encoder_backpressure";
            }
            // Per-node probes: ROI batch truncation and model failures
            if (g_) {
                g_->for_each_node([&](const std::string& name, const std::string& type, const std::unordered_map<std::string,std::string>& /*cfg*/){
                    (void)name;
                    if (type == "roi.batch.cuda") {
                        auto itid = std::string(name); // name not used in cast; rely on type
                        // dynamic cast via hidden knowledge of registry types
                        // We cannot fetch node object here; Graph::for_each_node exposes cfg; use with_node for live node
                    }
                });
                // use with_node to access live node objects
                for (const auto& probe : std::vector<std::pair<std::string,std::string>>{
                    {"roi.batch.cuda", "roi_batch.cuda"}, {"roi.batch", "roi_batch.cpu"}, {"model.ort", "model"}}) {
                    const std::string& t = probe.first; const std::string& tag = probe.second;
                    // iterate names by scanning nodes again to find names of type t
                    g_->for_each_node([&](const std::string& nm, const std::string& tp, const std::unordered_map<std::string,std::string>& cfg){
                        if (tp != t) return;
                        (void)cfg;
                        g_->with_node(nm, [&](va::analyzer::multistage::NodePtr& n, std::string& /*type*/, std::unordered_map<std::string,std::string>& /*cfg_mut*/){
                            if (t == "roi.batch.cuda") {
                                auto* rb = dynamic_cast<va::analyzer::multistage::NodeRoiBatchCuda*>(n.get());
                                if (rb) { int tot = rb->last_total_rois(); int used = rb->last_used_rois(); if (tot > used) { last_blocked_nodes_.push_back(tag); if (last_drain_reason_.empty()) last_drain_reason_ = "roi_truncated"; } }
                            } else if (t == "roi.batch") {
                                auto* rb = dynamic_cast<va::analyzer::multistage::NodeRoiBatch*>(n.get());
                                if (rb) { int tot = rb->last_total_rois(); int used = rb->last_used_rois(); if (tot > used) { last_blocked_nodes_.push_back(tag); if (last_drain_reason_.empty()) last_drain_reason_ = "roi_truncated"; } }
                            } else if (t == "model.ort") {
                                auto* mm = dynamic_cast<va::analyzer::multistage::NodeModel*>(n.get());
                                if (mm) { if (mm->infer_fail_count() > 0) { last_blocked_nodes_.push_back(tag); if (last_drain_reason_.empty()) last_drain_reason_ = "infer_failed_recent"; } }
                            }
                            return true;
                        });
                    });
                }
            }
        } catch (...) { /* ignore */ }
        return Status::OK();
    }
    Status HotSwapModel(const std::string& node, const std::string& uri) override {
        // Resolve node by name and replace underlying model session if node is NodeModel
        try {
            if (!g_) return Status::Internal("no graph");
            if (node.empty() || uri.empty()) return Status::InvalidArgument("missing node/model_uri");
            va::analyzer::multistage::NodeContext ctx{}; ctx.engine_registry = reinterpret_cast<void*>(em_);
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
        // Report runtime summary: phase + overrides breakdown + model targets
        try {
            std::ostringstream o;
            o << "{\"phase\":\"Ready\"";
            // overrides_keys
            if (!overrides_.empty()) { o << ",\"overrides_keys\":["; bool first=true; for (const auto& kv : overrides_) { if(!first) o<<","; first=false; o<<"\""<<kv.first<<"\""; } o << "]"; }
            // classify consumed/ignored (best-effort)
            if (!overrides_.empty()) {
                auto has_prefix = [](const std::string& k, const char* p){ return k.rfind(p, 0) == 0; };
                std::vector<std::string> consumed;
                std::vector<std::string> ignored;
                for (const auto& kv : overrides_) {
                    const auto& k = kv.first;
                    if (has_prefix(k, "engine.") || has_prefix(k, "engine.options.") ||
                        has_prefix(k, "params.") || has_prefix(k, "overrides.params.") ||
                        has_prefix(k, "node.") || k.rfind("type:", 0) == 0) {
                        consumed.push_back(k);
                    } else {
                        ignored.push_back(k);
                    }
                }
                if (!consumed.empty()) { o << ",\"overrides_consumed\":["; for (size_t i=0;i<consumed.size();++i){ if(i) o<<","; o<<"\""<<consumed[i]<<"\"";} o << "]"; }
                if (!ignored.empty())  { o << ",\"overrides_ignored\":[";  for (size_t i=0;i<ignored.size();++i){  if(i) o<<","; o<<"\""<<ignored[i]<<"\"";}  o << "]"; }
            }
            // Model targets snapshot
            if (g_) {
                bool appended=false;
                o << ",\"model_targets\":[";
                g_->for_each_node([&](const std::string& name, const std::string& type, const std::unordered_map<std::string,std::string>& cfg){
                    if (type == "model.ort") {
                        auto it = cfg.find("model_path");
                        std::string mp = (it == cfg.end()? std::string() : it->second);
                        if (appended) o << ",";
                        o << "{\"node\":\"" << name << "\",\"type\":\"" << type << "\",\"model_path\":\"" << mp << "\"}";
                        appended = true;
                    }
                });
                o << "]";
            }
            // Drain probe (if any)
            if (!last_blocked_nodes_.empty() || !last_drain_reason_.empty()) {
                o << ",\"drain_probe\":{\"blocked_nodes\":[";
                for (size_t i=0;i<last_blocked_nodes_.size();++i) { if(i) o<<","; o<<"\""<< last_blocked_nodes_[i] <<"\""; }
                o << "]";
                if (!last_drain_reason_.empty()) o << ",\"reason\":\"" << last_drain_reason_ << "\"";
                o << "}";
            }
            o << "}";
            return o.str();
        } catch (...) { return "{\"phase\":\"Ready\"}"; }
    }
private:
    Graph* g_ {nullptr};
    va::core::EngineManager* em_ {nullptr};
    bool opened_ {false};
    std::unordered_map<std::string,std::string> overrides_;
    std::vector<std::string> last_blocked_nodes_;
    std::string last_drain_reason_;
};

std::unique_ptr<IExecutor> GraphAdapterYaml::CreateExecutor(void* graph, std::string* /*err*/) {
    auto g = reinterpret_cast<Graph*>(graph);
    if (!g) return {};
    return std::make_unique<SimpleExecutor>(g, engine_manager_, overrides_cache_);
}

} } // namespace
