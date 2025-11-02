#pragma once

#include "analyzer/interfaces.hpp"

namespace va::analyzer {

class OverlayRendererCUDA : public IRenderer {
public:
    void setStream(void* s) { stream_ = s; }
    bool draw(const core::Frame& in, const core::ModelOutput& output, core::Frame& out) override;
private:
    mutable bool debug_printed_{false};
    void* stream_ {nullptr};
};

}
