#include "controlplane/controllers/pipeline_controller.hpp"
#include "core/logger.hpp"
#include <json/json.h>
#include <sstream>
#include <chrono>

namespace va { namespace control {

PipelineController::PipelineController(IGraphAdapter* adapter) : adapter_(adapter) {}

Status PipelineController::Apply(const PlainPipelineSpec& spec) {
    if (!adapter_) return Status::Internal("no adapter");
    if (spec.name.empty()) return Status::InvalidArgument("empty pipeline name");
    std::lock_guard<std::mutex> lk(mu_);
    auto t0 = std::chrono::steady_clock::now();
    std::string err;
    auto g = adapter_->BuildGraph(spec, &err);
    if (!g.get()) {
        auto t1 = std::chrono::steady_clock::now();
        uint64_t ms = static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count());
        // Record transient error under a stub runtime for status visibility (not persisted)
        VA_LOG_C(::va::core::LogLevel::Error, "control") << "apply BuildGraph failed name=" << spec.name << " err=" << err;
        return Status::InvalidArgument(std::string("BuildGraph failed: ")+err);
    }
    auto ex = adapter_->CreateExecutor(g.get(), &err);
    if (!ex) {
        auto t1 = std::chrono::steady_clock::now();
        uint64_t ms = static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count());
        VA_LOG_C(::va::core::LogLevel::Error, "control") << "apply CreateExecutor failed name=" << spec.name << " err=" << err;
        return Status::Internal(std::string("CreateExecutor failed: ")+err);
    }

    // stop existing
    if (auto it = pipelines_.find(spec.name); it != pipelines_.end()) {
        it->second.executor->Stop();
        pipelines_.erase(it);
    }

    Runtime rt;
    rt.graph = std::move(g);
    rt.executor = std::move(ex);
    rt.revision = spec.revision;
    rt.project = spec.project;
    rt.tags = spec.tags;
    if (!rt.executor->Start(&err)) {
        auto t1 = std::chrono::steady_clock::now();
        rt.last_apply_ms = static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count());
        rt.last_apply_error = std::string("executor start failed: ")+err;
        VA_LOG_C(::va::core::LogLevel::Error, "control") << "apply executor start failed name=" << spec.name << " err=" << err;
        return Status::Internal(rt.last_apply_error);
    }
    {
        auto t1 = std::chrono::steady_clock::now();
        rt.last_apply_ms = static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count());
        rt.last_apply_error.clear();
    }
    rt.ready.store(true, std::memory_order_release);
    pipelines_.emplace(std::piecewise_construct,
                       std::forward_as_tuple(spec.name),
                       std::forward_as_tuple(std::move(rt)));
    VA_LOG_C(::va::core::LogLevel::Info, "control") << "pipeline applied name=" << spec.name << " rev=" << spec.revision
                                                     << " project=" << rt.project;
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
    auto t0 = std::chrono::steady_clock::now();
    auto st = it->second.executor->Drain(timeout_sec);
    auto t1 = std::chrono::steady_clock::now();
    it->second.last_drain_ms = static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count());
    it->second.last_drain_timeout_sec = timeout_sec;
    it->second.last_drain_ok = st.ok();
    it->second.last_drain_blocked_nodes.clear();
    // best-effort parse of reason
    it->second.last_drain_reason = st.ok() ? std::string() : st.message();
    // Pull drain_probe from executor status if present
    try {
        std::string inner = it->second.executor->CollectStatusJson();
        Json::CharReaderBuilder b; std::string errs; std::istringstream is(inner); Json::Value tmp;
        if (Json::parseFromStream(b, is, &tmp, &errs)) {
            if (tmp.isObject() && tmp.isMember("drain_probe") && tmp["drain_probe"].isObject()) {
                const auto& dp = tmp["drain_probe"];
                if (dp.isMember("blocked_nodes") && dp["blocked_nodes"].isArray()) {
                    for (const auto& n : dp["blocked_nodes"]) if (n.isString()) it->second.last_drain_blocked_nodes.push_back(n.asString());
                }
                if (dp.isMember("reason") && dp["reason"].isString() && it->second.last_drain_reason.empty()) it->second.last_drain_reason = dp["reason"].asString();
            }
        }
    } catch (...) { /* ignore */ }
    return st;
}

std::string PipelineController::GetStatus(const std::string& name) {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = pipelines_.find(name);
    if (it == pipelines_.end()) return std::string("{\"phase\":\"NotFound\"}");
    // Merge executor status with controller metadata
    std::string inner = it->second.executor->CollectStatusJson();
    Json::Value data(Json::objectValue);
    try {
        Json::CharReaderBuilder b; std::string errs; std::istringstream is(inner); Json::Value tmp;
        if (Json::parseFromStream(b, is, &tmp, &errs)) data = tmp; else data["raw"] = inner;
    } catch (...) { data["raw"] = inner; }
    data["revision"] = it->second.revision;
    data["project"] = it->second.project;
    {
        Json::Value arr(Json::arrayValue); for (const auto& t : it->second.tags) arr.append(t); data["tags"] = arr;
    }
    data["last_apply_ms"] = static_cast<Json::UInt64>(it->second.last_apply_ms);
    if (!it->second.last_apply_error.empty()) data["last_apply_error"] = it->second.last_apply_error;
    // drain snapshot
    {
        Json::Value d(Json::objectValue);
        d["timeout_sec"] = it->second.last_drain_timeout_sec;
        d["elapsed_ms"] = static_cast<Json::UInt64>(it->second.last_drain_ms);
        d["ok"] = it->second.last_drain_ok;
        if (!it->second.last_drain_reason.empty()) d["reason"] = it->second.last_drain_reason;
        if (!it->second.last_drain_blocked_nodes.empty()) {
            Json::Value arr(Json::arrayValue); for (const auto& n : it->second.last_drain_blocked_nodes) arr.append(n); d["blocked_nodes"] = arr;
        } else {
            d["blocked_nodes"] = Json::arrayValue;
        }
        data["drain"] = d;
    }
    Json::StreamWriterBuilder w; w["indentation"] = ""; return Json::writeString(w, data);
}

} } // namespace
