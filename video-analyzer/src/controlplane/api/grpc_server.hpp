#pragma once

#include <memory>
#include <string>

namespace va { namespace app { class Application; } }
namespace va { namespace control {

class PipelineController; // fwd

class AnalyzerControlService { };

struct OpaquePtr; // from interfaces

OpaquePtr StartGrpcServer(const std::string& /*addr*/, AnalyzerControlService* /*svc*/);
OpaquePtr StartGrpcServer(const std::string& addr, PipelineController* ctl);
OpaquePtr StartGrpcServer(const std::string& addr, PipelineController* ctl, va::app::Application* app);

} } // namespace

