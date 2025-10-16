#pragma once

#include "core/utils.hpp"

#include <memory>
#include <string>

namespace va::media {

struct SourceStats {
    double fps {0.0};
    double avg_latency_ms {0.0};
    uint64_t last_frame_id {0};
};

class IFrameSource {
public:
    virtual ~IFrameSource() = default;
    virtual bool start() = 0;
    virtual void stop() = 0;
    virtual bool read(core::Frame& frame) = 0;
    virtual SourceStats stats() const = 0;
};

class ISwitchableSource : public IFrameSource {
public:
    virtual bool switchUri(const std::string& uri) = 0;
};

using IFrameSourcePtr = std::shared_ptr<IFrameSource>;
using ISwitchableSourcePtr = std::shared_ptr<ISwitchableSource>;

} // namespace va::media
