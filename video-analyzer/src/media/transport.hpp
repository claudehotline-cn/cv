#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

namespace va::media {

class ITransport {
public:
    virtual ~ITransport() = default;
    virtual bool connect(const std::string& endpoint) = 0;
    virtual bool send(const std::string& track_id, const uint8_t* data, size_t size) = 0;
    virtual void disconnect() = 0;

    struct Stats {
        bool connected {false};
        uint64_t packets {0};
        uint64_t bytes {0};
    };

    virtual Stats stats() const = 0;
};

} // namespace va::media
