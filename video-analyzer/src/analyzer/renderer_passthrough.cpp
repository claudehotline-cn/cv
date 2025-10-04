#include "analyzer/renderer_passthrough.hpp"

namespace va::analyzer {

bool PassthroughRenderer::draw(const core::Frame& in, const core::ModelOutput& /*output*/, core::Frame& out) {
    out = in;
    return true;
}

bool PassthroughRenderer::draw(const core::FrameSurface& in,
                               const core::ModelOutput& /*output*/,
                               core::FrameSurface& out) {
    out = in;
    return true;
}

} // namespace va::analyzer
