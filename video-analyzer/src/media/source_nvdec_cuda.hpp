#pragma once

#include "media/source_switchable_rtsp.hpp"

// NOTE: This is a scaffolding implementation for a future NVDEC-based source.
// It preserves the existing ISwitchableSource interface and safely falls back
// to CPU/OpenCV decoding until real NVDEC is wired in.

namespace va::media {

class NvdecRtspSource : public ISwitchableSource {
public:
    explicit NvdecRtspSource(std::string uri);
    ~NvdecRtspSource() override = default;

    bool start() override;
    void stop() override;
    bool read(va::core::Frame& frame) override;
    SourceStats stats() const override;
    bool switchUri(const std::string& uri) override;

private:
    // Temporary CPU fallback path reused internally
    SwitchableRtspSource cpu_fallback_;
};

} // namespace va::media

// Factory symbol used by composition_root to avoid direct header coupling
namespace va::media {
    std::shared_ptr<ISwitchableSource> makeNvdecSource(const std::string& uri);
}

