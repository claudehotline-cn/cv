#include "control_plane_embedded/exporters/prometheus_exporter.hpp"

namespace va { namespace control {

bool PrometheusExporter::Start(const std::string&, int) {
    // 占位：未集成 HTTP 服务器。保留采集线程结构，便于后续接线到 REST 层。
    running_.store(true);
    th_ = std::thread([this]() {
        while (running_.load()) {
            // 这里可定期拉取 collector_() 结果并缓存到共享位置，由 REST /metrics 暴露
            std::this_thread::sleep_for(std::chrono::seconds(5));
        }
    });
    return true;
}

void PrometheusExporter::Stop() {
    if (!running_.load()) return;
    running_.store(false);
    if (th_.joinable()) th_.join();
}

} } // namespace

