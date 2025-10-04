#pragma once

#include "analyzer/interfaces.hpp"

namespace va::analyzer {

class PassthroughRenderer : public IRenderer {
public:
    bool draw(const core::Frame& in, const core::ModelOutput& /*output*/, core::Frame& out) override;
    bool draw(const core::FrameSurface& in,
              const core::ModelOutput& /*output*/,
              core::FrameSurface& out) override;
};

} // namespace va::analyzer
