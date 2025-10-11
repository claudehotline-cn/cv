#pragma once

#include <string>

namespace va { namespace control {

// 与 video-source-manager 的桥接占位：后续可替换为共享内存/IPC/gRPC streaming
class FromVsmLink {
public:
    bool Attach(const std::string& /*attach_id*/) { return true; }
    void Detach(const std::string& /*attach_id*/) {}
};

} } // namespace

