#pragma once

#include "analyzer/interfaces.hpp"

namespace va::analyzer {

class PassthroughRenderer : public IRenderer {
public:
    bool draw(const core::Frame& in, const core::ModelOutput& /*output*/, core::Frame& out) override;
};

} // namespace va::analyzer
