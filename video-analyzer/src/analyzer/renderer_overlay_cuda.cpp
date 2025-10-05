#include "analyzer/renderer_overlay_cuda.hpp"
#include "analyzer/renderer_overlay_cpu.hpp"

namespace va::analyzer {

bool OverlayRendererCUDA::draw(const core::Frame& in, const core::ModelOutput& output, core::Frame& out) {
    // Placeholder: until full GPU overlay kernels are implemented, fallback to CPU overlay
    OverlayRendererCPU cpu;
    return cpu.draw(in, output, out);
}

}

