#pragma once

#include "core/utils.hpp"

#include <string>
#include <vector>

namespace va::media {

class IEncoder {
public:
    virtual ~IEncoder() = default;
    struct Settings {
        int width {0};
        int height {0};
        int fps {0};
        int bitrate_kbps {0};
        int gop {0};
        int bframes {0};
        bool zero_latency {true};
        std::string preset;
        std::string tune;
        std::string profile;
        std::string codec {"h264"};
    };

    virtual bool open(const Settings& settings) = 0;
    struct Packet {
        std::vector<uint8_t> data;
        bool keyframe {false};
        double pts_ms {0.0};
    };

    virtual bool encode(const core::Frame& frame, Packet& out_packet) = 0;
    virtual void close() = 0;
};

} // namespace va::media
