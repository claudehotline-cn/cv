#include "control_plane_embedded/controllers/pipeline_controller.hpp"
#include "core/logger.hpp"

namespace va { namespace control {

PipelineController::PipelineController(IGraphAdapter* adapter) : adapter_(adapter) {}

Status PipelineController::Apply(const PlainPipelineSpec& spec) {
    if (!adapter_) return Status::Internal("no adapter");
    if (spec.name.empty()) return Status::InvalidArgument("empty pipeline name");
    std::lock_guard<std::mutex> lk(mu_);
    std::string err;
    auto g = adapter_->BuildGraph(spec, &err);
    if (!g.get()) return Status::InvalidArgument(std::string("BuildGraph failed: ")+err);
    auto ex = adapter_->CreateExecutor(g.get(), &err);
    if (!ex) return Status::Internal(std::string("CreateExecutor failed: ")+err);

    // stop existing
    if (auto it = pipelines_.find(spec.name); it != pipelines_.end()) {
        it->second.executor->Stop();
        pipelines_.erase(it);
    }

    Runtime rt;
    rt.graph = std::move(g);
    rt.executor = std::move(ex);
    rt.revision = spec.revision;
    if (!rt.executor->Start(&err)) {
        return Status::Internal(std::string("executor start failed: ")+err);
    }
    rt.ready.store(true, std::memory_order_release);
    pipelines_.emplace(std::piecewise_construct,
                       std::forward_as_tuple(spec.name),
                       std::forward_as_tuple(std::move(rt)));
    VA_LOG_C(::va::core::LogLevel::Info, "control") << "pipeline applied name=" << spec.name << " rev=" << spec.revision;
    return Status::OK();
}

Status PipelineController::Remove(const std::string& name) {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = pipelines_.find(name);
    if (it == pipelines_.end()) return Status::NotFound("pipeline not found");
    it->second.executor->Stop();
    pipelines_.erase(it);
    VA_LOG_C(::va::core::LogLevel::Info, "control") << "pipeline removed name=" << name;
    return Status::OK();
}

Status PipelineController::HotSwapModel(const std::string& name, const std::string& node, const std::string& uri) {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = pipelines_.find(name);
    if (it == pipelines_.end()) return Status::NotFound("pipeline not found");
    return it->second.executor->HotSwapModel(node, uri);
}

Status PipelineController::Drain(const std::string& name, int timeout_sec) {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = pipelines_.find(name);
    if (it == pipelines_.end()) return Status::NotFound("pipeline not found");
    return it->second.executor->Drain(timeout_sec);
}

std::string PipelineController::GetStatus(const std::string& name) {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = pipelines_.find(name);
    if (it == pipelines_.end()) return std::string("{\"phase\":\"NotFound\"}");
    return it->second.executor->CollectStatusJson();
}

} } // namespace
