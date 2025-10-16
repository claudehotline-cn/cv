#pragma once

#include "core/engine_manager.hpp"
#include "core/factories.hpp"
#include "core/pipeline.hpp"

#include <memory>

namespace va::core {

class PipelineBuilder {
public:
    PipelineBuilder(const Factories& factories, EngineManager& engine_manager);

    std::shared_ptr<Pipeline> build(const SourceConfig& source_cfg,
                                    const FilterConfig& filter_cfg,
                                    const EncoderConfig& encoder_cfg,
                                    const TransportConfig& transport_cfg) const;

private:
    const Factories& factories_;
    EngineManager& engine_manager_;
};

} // namespace va::core
