#pragma once

#include "analyzer/interfaces.hpp"
#include "analyzer/multistage/interfaces.hpp"
#include "core/engine_manager.hpp"
#include "analyzer/triton_session.hpp"

#include <memory>
#include <string>

namespace va::analyzer {

struct ProviderDecision {
    std::string requested; // e.g. "tensorrt" | "cuda" | "cpu" ("rtx" 将被视为 "tensorrt")
    std::string resolved;  // best-effort resolution hint; may be updated by session later
};

// Create a model session according to EngineDescriptor + NodeContext hints.
// For M0 this always returns an OrtModelSession with provider preference encoded
// in its Options; fallback order: tensorrt -> cuda -> cpu. （RTX EP 暂不实现）
std::shared_ptr<IModelSession>
create_model_session(const va::core::EngineDescriptor& engine,
                     const va::analyzer::multistage::NodeContext& ctx,
                     ProviderDecision* decision = nullptr);

} // namespace va::analyzer
