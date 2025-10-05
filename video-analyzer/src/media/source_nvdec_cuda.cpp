#include "media/source_nvdec_cuda.hpp"

namespace va::media {

NvdecRtspSource::NvdecRtspSource(std::string uri)
    : cpu_fallback_(std::move(uri)) {}

bool NvdecRtspSource::start() {
    // TODO: replace with real NVDEC init; for now use CPU path
    return cpu_fallback_.start();
}

void NvdecRtspSource::stop() {
    cpu_fallback_.stop();
}

bool NvdecRtspSource::read(va::core::Frame& frame) {
    // TODO: when NVDEC is ready, return GPU surface-backed Frame/FrameSurface
    return cpu_fallback_.read(frame);
}

SourceStats NvdecRtspSource::stats() const {
    return cpu_fallback_.stats();
}

bool NvdecRtspSource::switchUri(const std::string& uri) {
    return cpu_fallback_.switchUri(uri);
}

std::shared_ptr<ISwitchableSource> makeNvdecSource(const std::string& uri) {
    return std::make_shared<NvdecRtspSource>(uri);
}

} // namespace va::media
