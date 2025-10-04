#include "analyzer/analyzer.hpp"

#include <utility>

namespace va::analyzer {

namespace {

void ensureTensorHandle(core::TensorView& tensor) {
    tensor.handle.host_ptr = tensor.data;
    tensor.handle.device_ptr = tensor.device_data;
    tensor.handle.bytes = tensor.bytes;
    tensor.handle.pitch = 0;
    tensor.handle.width = 0;
    tensor.handle.height = 0;
    tensor.handle.stream = nullptr;
    tensor.handle.location = tensor.on_gpu ? core::MemoryLocation::Device : core::MemoryLocation::Host;
    tensor.handle.format = core::PixelFormat::Unknown;
}

} // namespace

Analyzer::Analyzer() = default;

void Analyzer::setPreprocessor(std::shared_ptr<IPreprocessor> preprocessor) {
    preprocessor_ = std::move(preprocessor);
}

void Analyzer::setSession(std::shared_ptr<IModelSession> session) {
    session_ = std::move(session);
}

void Analyzer::setPostprocessor(std::shared_ptr<IPostprocessor> postprocessor) {
    postprocessor_ = std::move(postprocessor);
}

void Analyzer::setRenderer(std::shared_ptr<IRenderer> renderer) {
    renderer_ = std::move(renderer);
}

void Analyzer::setUseGpuHint(bool value) {
    use_gpu_hint_ = value;
}

bool Analyzer::analyze(const core::Frame& in,
                       core::Frame& out,
                       core::FrameSurface* gpu_out) {
    if (!preprocessor_ || !session_ || !postprocessor_ || !renderer_) {
        return false;
    }

    if (gpu_out) {
        *gpu_out = {};
    }

    const core::FrameSurface input_surface = va::core::makeSurfaceFromFrame(in);

    core::TensorView tensor;
    core::LetterboxMeta meta;
    if (!preprocessor_->run(input_surface, tensor, meta)) {
        if (!preprocessor_->run(in, tensor, meta)) {
            return false;
        }
    }
    ensureTensorHandle(tensor);

    std::vector<core::TensorView> outputs;
    if (!session_->run(tensor, outputs)) {
        return false;
    }
    for (auto& view : outputs) {
        ensureTensorHandle(view);
    }

    core::ModelOutput model_output;
    if (!postprocessor_->run(outputs, meta, model_output)) {
        return false;
    }

    if (params_) {
        for (auto& box : model_output.boxes) {
            box.score = std::min(std::max(box.score, 0.0f), 1.0f);
        }
    }

    core::FrameSurface gpu_render_surface;
    if (renderer_->draw(input_surface, model_output, gpu_render_surface)) {
        if (gpu_out) {
            *gpu_out = gpu_render_surface;
            return true;
        }
        if (va::core::surfaceToFrame(gpu_render_surface, out)) {
            return true;
        }
    }

    if (!renderer_->draw(in, model_output, out)) {
        return false;
    }

    if (gpu_out) {
        *gpu_out = va::core::makeSurfaceFromFrame(out);
    }
    return true;
}

bool Analyzer::switchModel(const std::string& model_id) {
    if (!session_) {
        return false;
    }
    if (!session_->loadModel(model_id, use_gpu_hint_)) {
        return false;
    }
    return true;
}

bool Analyzer::switchTask(const std::string& /*task_id*/) {
    // TODO: implement task switching in subsequent stages
    return true;
}

bool Analyzer::updateParams(std::shared_ptr<AnalyzerParams> params) {
    params_ = std::move(params);
    return static_cast<bool>(params_);
}

} // namespace va::analyzer
