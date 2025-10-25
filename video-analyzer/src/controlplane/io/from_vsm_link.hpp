#pragma once

#include <string>

namespace va { namespace control {

class FromVsmLink {
public:
    bool Attach(const std::string& /*attach_id*/) { return true; }
    void Detach(const std::string& /*attach_id*/) {}
};

} } // namespace

