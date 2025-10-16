#include "analyzer/renderer_passthrough.hpp"

namespace va::analyzer {

bool PassthroughRenderer::draw(const core::Frame& in, const core::ModelOutput& /*output*/, core::Frame& out) {
    out = in;
    return true;
}

} // namespace va::analyzer
