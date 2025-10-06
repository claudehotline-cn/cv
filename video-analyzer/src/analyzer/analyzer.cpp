#include "analyzer/analyzer.hpp"
#include "core/logger.hpp"

#include <utility>
#include <chrono>

namespace va::analyzer {

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

bool Analyzer::analyze(const core::Frame& in, core::Frame& out) {
    if (!preprocessor_ || !session_ || !postprocessor_ || !renderer_) {
        return false;
    }

    core::TensorView tensor;
    core::LetterboxMeta meta;
    auto t0 = std::chrono::high_resolution_clock::now();
    if (!preprocessor_->run(in, tensor, meta)) {
        VA_LOG_DEBUG() << "[Analyzer] preprocessor failed (in: " << in.width << "x" << in.height
                       << ", has_device=" << (in.has_device_surface?"1":"0") << ")";
        return false;
    }
    auto t1 = std::chrono::high_resolution_clock::now();

    std::vector<core::TensorView> outputs;
    if (!session_->run(tensor, outputs)) {
        VA_LOG_DEBUG() << "[Analyzer] session.run failed (tensor on_gpu=" << (tensor.on_gpu?"1":"0")
                       << ", shape=" << (tensor.shape.size()>0?tensor.shape[0]:0) << "x"
                       << (tensor.shape.size()>1?tensor.shape[1]:0) << "x"
                       << (tensor.shape.size()>2?tensor.shape[2]:0) << ")";
        return false;
    }
    auto t2 = std::chrono::high_resolution_clock::now();

    core::ModelOutput model_output;
    if (!postprocessor_->run(outputs, meta, model_output)) {
        VA_LOG_DEBUG() << "[Analyzer] postprocessor failed (outputs=" << outputs.size()
                       << ", letterbox: in=" << meta.input_width << "x" << meta.input_height
                       << " orig=" << meta.original_width << "x" << meta.original_height
                       << " scale=" << meta.scale << ")";
        return false;
    }
    auto t3 = std::chrono::high_resolution_clock::now();

    if (params_) {
        for (auto& box : model_output.boxes) {
            box.score = std::min(std::max(box.score, 0.0f), 1.0f);
        }
    }
    auto t4 = std::chrono::high_resolution_clock::now();
    bool ok = renderer_->draw(in, model_output, out);
    auto t5 = std::chrono::high_resolution_clock::now();
    if (!ok) {
        VA_LOG_DEBUG() << "[Analyzer] renderer.draw failed (boxes=" << model_output.boxes.size() << ")";
    } else {
        auto ms = [](auto a, auto b){ return std::chrono::duration_cast<std::chrono::milliseconds>(b-a).count(); };
        VA_LOG_DEBUG() << "[Analyzer] timings ms: preproc=" << ms(t0,t1)
                       << " infer=" << ms(t1,t2)
                       << " postproc=" << ms(t2,t3)
                       << " render=" << ms(t4,t5)
                       << ", boxes=" << model_output.boxes.size();
    }
    return ok;
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
