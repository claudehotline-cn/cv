#include "analyzer/preproc_letterbox_cpu.hpp"

#include <cstring>
#include <opencv2/imgproc.hpp>

namespace va::analyzer {

LetterboxPreprocessorCPU::LetterboxPreprocessorCPU(int input_width, int input_height)
    : input_width_(input_width), input_height_(input_height) {}

bool LetterboxPreprocessorCPU::run(const core::Frame& in, core::TensorView& out, core::LetterboxMeta& meta) {
    if (in.width <= 0 || in.height <= 0 || in.bgr.empty()) {
        return false;
    }

    const int target_w = input_width_ > 0 ? input_width_ : in.width;
    const int target_h = input_height_ > 0 ? input_height_ : in.height;

    meta.input_width = target_w;
    meta.input_height = target_h;
    meta.original_width = in.width;
    meta.original_height = in.height;

    cv::Mat src(in.height, in.width, CV_8UC3, const_cast<uint8_t*>(in.bgr.data()));

    const float scale = std::min(static_cast<float>(target_w) / static_cast<float>(in.width),
                                 static_cast<float>(target_h) / static_cast<float>(in.height));
    const int resized_w = static_cast<int>(std::round(in.width * scale));
    const int resized_h = static_cast<int>(std::round(in.height * scale));
    const int pad_w = target_w - resized_w;
    const int pad_h = target_h - resized_h;
    const int pad_left = pad_w / 2;
    const int pad_top = pad_h / 2;

    meta.scale = scale;
    meta.pad_x = pad_left;
    meta.pad_y = pad_top;

    cv::Mat resized;
    cv::resize(src, resized, cv::Size(resized_w, resized_h));

    cv::Mat letterboxed(target_h, target_w, CV_8UC3, cv::Scalar(114, 114, 114));
    resized.copyTo(letterboxed(cv::Rect(pad_left, pad_top, resized_w, resized_h)));

    cv::Mat letterboxed_float;
    letterboxed.convertTo(letterboxed_float, CV_32F, 1.0f / 255.0f);

    std::vector<cv::Mat> channels(3);
    cv::split(letterboxed_float, channels);

    const size_t plane_size = static_cast<size_t>(target_w) * static_cast<size_t>(target_h);
    buffer_.resize(plane_size * 3);

    for (size_t c = 0; c < 3; ++c) {
        std::memcpy(buffer_.data() + c * plane_size, channels[c].ptr<float>(), plane_size * sizeof(float));
    }

    out.data = buffer_.data();
    out.shape = {1, 3, target_h, target_w};
    out.dtype = core::DType::F32;
    out.on_gpu = false;

    return true;
}

} // namespace va::analyzer
