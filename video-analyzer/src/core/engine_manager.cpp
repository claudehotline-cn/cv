#include "core/engine_manager.hpp"
#include "core/logger.hpp"

#include <utility>

namespace va::core {

EngineManager::EngineManager() = default;

bool EngineManager::setEngine(EngineDescriptor descriptor) {
    std::scoped_lock lock(mutex_);
    try {
        std::string keys; for (const auto& kv : descriptor.options) { keys += kv.first; keys += ","; }
        if (!keys.empty()) keys.pop_back();
        auto gm = descriptor.options.find("graph_id");
        auto my = descriptor.options.find("multistage_yaml");
        auto mu = descriptor.options.find("use_multistage");
        VA_LOG_C(::va::core::LogLevel::Info, "composition")
            << "engine.set(commit) type='" << descriptor.name
            << "' provider='" << (descriptor.provider.empty()? descriptor.name : descriptor.provider)
            << "' device=" << descriptor.device_index
            << " use_multistage='" << (mu!=descriptor.options.end()? mu->second : std::string(""))
            << "' graph_id='" << (gm!=descriptor.options.end()? gm->second : std::string(""))
            << "' yaml='" << (my!=descriptor.options.end()? my->second : std::string(""))
            << "' option_keys=[" << keys << "]";
    } catch (...) { /* best-effort logging */ }
    current_ = std::move(descriptor);
    runtime_status_.provider = current_.provider.empty() ? current_.name : current_.provider;
    runtime_status_.gpu_active = false;
    runtime_status_.io_binding = false;
    runtime_status_.device_binding = false;
    runtime_status_.cpu_fallback = false;
    return true;
}

EngineDescriptor EngineManager::currentEngine() const {
    std::scoped_lock lock(mutex_);
    return current_;
}

bool EngineManager::prewarm(const std::string& /*model_path*/) {
    // TODO: integrate ONNX/TensorRT prewarm in later stages
    return true;
}

void EngineManager::updateRuntimeStatus(EngineRuntimeStatus status) {
    std::scoped_lock lock(mutex_);
    runtime_status_ = std::move(status);
}

EngineRuntimeStatus EngineManager::currentRuntimeStatus() const {
    std::scoped_lock lock(mutex_);
    return runtime_status_;
}

} // namespace va::core
