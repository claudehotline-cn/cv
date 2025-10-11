#pragma once

#include <string>
#include <thread>
#include <atomic>
#include <functional>

namespace va { namespace control {

class PrometheusExporter {
public:
    using CollectorFn = std::function<std::string()>;
    PrometheusExporter() = default;
    ~PrometheusExporter() { Stop(); }
    void SetCollector(CollectorFn fn) { collector_ = std::move(fn); }
    bool Start(const std::string& /*host*/, int /*port*/);
    void Stop();
private:
    CollectorFn collector_;
    std::thread th_;
    std::atomic<bool> running_{false};
};

} } // namespace

