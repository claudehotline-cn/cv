#include "analyzer/renderer_overlay_cpu.hpp"

#include <opencv2/imgproc.hpp>

namespace va::analyzer {

static cv::Scalar colorForClass(int cls) {
    static const cv::Scalar palette[] = {
        {255, 56, 56}, {255, 157, 151}, {255, 112, 31}, {255, 178, 29}, {207, 210, 49},
        {72, 249, 10}, {146, 204, 23}, {61, 219, 134}, {26, 147, 52}, {0, 212, 187},
        {44, 153, 168}, {0, 194, 255}, {52, 69, 147}, {100, 115, 255}, {0, 24, 236},
        {132, 56, 255}, {82, 0, 133}, {203, 56, 255}, {255, 149, 200}, {255, 55, 199}
    };
    return palette[cls % (sizeof(palette)/sizeof(palette[0]))];
}

bool OverlayRendererCPU::draw(const core::Frame& in, const core::ModelOutput& output, core::Frame& out) {
    if (in.width <= 0 || in.height <= 0 || in.bgr.empty()) {
        return false;
    }
    out = in; // copy frame metadata and pixel buffer
    cv::Mat img(out.height, out.width, CV_8UC3, out.bgr.data());

    const int base = std::min(out.width, out.height);
    const int thickness = std::max(2, base / 400);
    const double fontScale = std::max(0.4, base / 1000.0);

    for (const auto& box : output.boxes) {
        const int x1 = std::max(0, static_cast<int>(std::round(box.x1)));
        const int y1 = std::max(0, static_cast<int>(std::round(box.y1)));
        const int x2 = std::min(out.width - 1, static_cast<int>(std::round(box.x2)));
        const int y2 = std::min(out.height - 1, static_cast<int>(std::round(box.y2)));
        if (x2 <= x1 || y2 <= y1) continue;
        const cv::Scalar color = colorForClass(box.cls);
        cv::rectangle(img, cv::Point(x1, y1), cv::Point(x2, y2), color, thickness, cv::LINE_AA);

        char label[64];
        std::snprintf(label, sizeof(label), "id:%d %.0f%%", box.cls, box.score * 100.0f);
        int baseline = 0;
        cv::Size sz = cv::getTextSize(label, cv::FONT_HERSHEY_SIMPLEX, fontScale, thickness, &baseline);
        int lx1 = x1;
        int ly1 = std::max(0, y1 - sz.height - 6);
        int lx2 = std::min(out.width - 1, x1 + sz.width + 6);
        int ly2 = std::max(0, y1);
        cv::rectangle(img, cv::Point(lx1, ly1), cv::Point(lx2, ly2), color, cv::FILLED);
        cv::putText(img, label, cv::Point(x1 + 3, y1 - 3), cv::FONT_HERSHEY_SIMPLEX, fontScale, cv::Scalar(255,255,255), thickness, cv::LINE_AA);
    }

    return true;
}

} // namespace va::analyzer

