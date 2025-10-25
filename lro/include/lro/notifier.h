#pragma once
#include <functional>
#include <memory>
#include <string>
#include "lro/operation.h"

namespace lro {

// 通知 SPI：宿主可对接 SSE/WS/Webhook/MQ
struct INotifier {
    virtual ~INotifier() = default;
    virtual void notify(const std::string& opId, const std::string& jsonPayload) = 0;
};

// 简易回调实现
struct CallbackNotifier : public INotifier {
    std::function<void(const std::string&, const std::string&)> cb;
    explicit CallbackNotifier(std::function<void(const std::string&, const std::string&)> f)
        : cb(std::move(f)) {}
    void notify(const std::string& id, const std::string& payload) override {
        if (cb) cb(id, payload);
    }
};

} // namespace lro

