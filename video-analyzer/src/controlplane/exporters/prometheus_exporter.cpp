#include "controlplane/exporters/prometheus_exporter.hpp"

namespace va { namespace control {

void PrometheusExporter::registerDefaultMetrics() {
    // placeholder: register default controlplane metrics
}

std::string PrometheusExporter::renderMetrics() {
    // placeholder output; actual metrics rendering should be integrated with VA metrics builder
    return "# TYPE cp_up gauge\ncp_up 1\n";
}

} } // namespace

