#pragma once

#include <string>

namespace va { namespace control {

struct PrometheusExporter {
    static void registerDefaultMetrics();
    static std::string renderMetrics();
};

} } // namespace

