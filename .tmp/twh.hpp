#pragma once

#include "media/transport.hpp"

#include <memory>
#include <mutex>
#include <string>

namespace va::media {

class WebRTCDataChannelTransport : public ITransport {
public:
    WebRTCDataChannelTransport();
    ~WebRTCDataChannelTransport() override;

    bool connect(const std::string& endpoint) override;
    bool send(const std::string& track_id, const uint8_t* data, size_t size) override;
    void disconnect() override;
    Stats stats() const override;

private:
    struct Impl;
    std::shared_ptr<Impl> impl_;
};

} // namespace va::media


