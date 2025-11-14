#pragma once

#include "analyzer/interfaces.hpp"

namespace va::analyzer {

class YoloDetectionPostprocessor : public IPostprocessor {
public:
    void setThresholds(float conf, float iou) { conf_thr_ = conf; nms_iou_thr_ = iou; }
    bool run(const std::vector<core::TensorView>& raw_outputs,
             const core::LetterboxMeta& meta,
             core::ModelOutput& output) override;
private:
    float conf_thr_ { -1.0f };
    float nms_iou_thr_ { -1.0f };
};

#ifdef USE_CUDA
class YoloDetectionPostprocessorCUDA : public IPostprocessor {
public:
    void setStream(void* s) { stream_ = s; }
    void setPreferFp16(bool v) { prefer_fp16_ = v; }
    void setThresholds(float conf, float iou) { conf_thr_ = conf; nms_iou_thr_ = iou; }
    bool run(const std::vector<core::TensorView>& raw_outputs,
             const core::LetterboxMeta& meta,
             core::ModelOutput& output) override;
private:
    void* stream_ {nullptr};
    bool prefer_fp16_ {false};
    float conf_thr_ { -1.0f };
    float nms_iou_thr_ { -1.0f };
};
#endif

} // namespace va::analyzer
