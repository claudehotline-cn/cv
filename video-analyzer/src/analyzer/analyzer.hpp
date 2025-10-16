#pragma once

#include "analyzer/interfaces.hpp"

#include <memory>
#include <string>

namespace va::analyzer {

struct AnalyzerParams {
    float confidence_threshold {0.25f};
    float iou_threshold {0.45f};
};

class Analyzer : public IFrameFilter {
public:
    Analyzer();

    void setPreprocessor(std::shared_ptr<IPreprocessor> preprocessor);
    void setSession(std::shared_ptr<IModelSession> session);
    void setPostprocessor(std::shared_ptr<IPostprocessor> postprocessor);
    void setRenderer(std::shared_ptr<IRenderer> renderer);
    void setUseGpuHint(bool value);

    bool analyze(const core::Frame& in, core::Frame& out);

    bool process(const core::Frame& in, core::Frame& out) override { return analyze(in, out); }

    bool switchModel(const std::string& model_id);
    bool switchTask(const std::string& task_id);
    bool updateParams(std::shared_ptr<AnalyzerParams> params);

private:
    std::shared_ptr<IPreprocessor> preprocessor_;
    std::shared_ptr<IModelSession> session_;
    std::shared_ptr<IPostprocessor> postprocessor_;
    std::shared_ptr<IRenderer> renderer_;
    std::shared_ptr<AnalyzerParams> params_;
    bool use_gpu_hint_ {false};
};

} // namespace va::analyzer
