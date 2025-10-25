#pragma once

#include "controlplane/interfaces.hpp"
#include <unordered_map>
#include <vector>
#include <memory>
#include <mutex>
#include <atomic>

namespace va { namespace control {

class PipelineController {
public:
    explicit PipelineController(IGraphAdapter* adapter);
    Status Apply(const PlainPipelineSpec& spec);
    Status Remove(const std::string& name);
    Status HotSwapModel(const std::string& name, const std::string& node, const std::string& uri);
    Status Drain(const std::string& name, int timeout_sec);
    std::string GetStatus(const std::string& name);

private:
    struct Runtime {
        OpaquePtr                  graph;     // holds multistage::Graph
        std::unique_ptr<IExecutor> executor;
        std::string                revision;
        std::string                project;
        std::vector<std::string>   tags;
        std::atomic<bool>          ready{false};
        // Status extras
        uint64_t                   last_apply_ms {0};
        std::string                last_apply_error;
        // Drain extras
        uint64_t                   last_drain_ms {0};
        int                        last_drain_timeout_sec {0};
        bool                       last_drain_ok {false};
        std::vector<std::string>   last_drain_blocked_nodes; // best-effort
        std::string                last_drain_reason;
        Runtime() = default;
        Runtime(const Runtime&) = delete;
        Runtime& operator=(const Runtime&) = delete;
        Runtime(Runtime&& o) noexcept {
            graph = std::move(o.graph);
            executor = std::move(o.executor);
            revision = std::move(o.revision);
            ready.store(o.ready.load(std::memory_order_acquire), std::memory_order_release);
            o.ready.store(false, std::memory_order_release);
        }
        Runtime& operator=(Runtime&& o) noexcept {
            if (this != &o) {
                graph = std::move(o.graph);
                executor = std::move(o.executor);
                revision = std::move(o.revision);
                ready.store(o.ready.load(std::memory_order_acquire), std::memory_order_release);
                o.ready.store(false, std::memory_order_release);
            }
            return *this;
        }
    };
    std::mutex mu_;
    std::unordered_map<std::string, Runtime> pipelines_;
    IGraphAdapter* adapter_ {nullptr};
};

} } // namespace
