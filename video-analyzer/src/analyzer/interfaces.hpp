#pragma once

#include "core/utils.hpp"

#include <memory>
#include <string>
#include <vector>

namespace va::analyzer {

using va::core::Frame;
using va::core::FrameSurface;
using va::core::LetterboxMeta;
using va::core::ModelOutput;
using va::core::TensorView;

struct IPreprocessor {
    virtual ~IPreprocessor() = default;
    virtual bool run(const Frame& in, TensorView& out, LetterboxMeta& meta) = 0;
    // Optional GPU-aware entry. Default returns false; implementers may override.
    virtual bool run(const FrameSurface& /*in*/, TensorView& /*out*/, LetterboxMeta& /*meta*/) { return false; }
};

struct IModelSession {
    virtual ~IModelSession() = default;
    virtual bool loadModel(const std::string& model_path, bool use_gpu) = 0;
    virtual bool run(const TensorView& input, std::vector<TensorView>& outputs) = 0;
};

struct IPostprocessor {
    virtual ~IPostprocessor() = default;
    virtual bool run(const std::vector<TensorView>& raw_outputs,
                     const LetterboxMeta& meta,
                     ModelOutput& output) = 0;
};

struct IRenderer {
    virtual ~IRenderer() = default;
    virtual bool draw(const Frame& in, const ModelOutput& output, Frame& out) = 0;
    // Optional GPU-aware entry. Default returns false; implementers may override.
    virtual bool draw(const FrameSurface& /*in*/, const ModelOutput& /*output*/, FrameSurface& /*out*/) { return false; }
};

struct IFrameFilter {
    virtual ~IFrameFilter() = default;
    virtual bool process(const Frame& in, Frame& out) = 0;
    // Optional GPU-aware entry. Default returns false; implementers may override.
    virtual bool process(const FrameSurface& /*in*/, FrameSurface& /*out*/) { return false; }
};

} // namespace va::analyzer

