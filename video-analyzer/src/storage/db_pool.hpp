#pragma once

#include "ConfigLoader.hpp"

#include <memory>
#include <string>

namespace va::storage {

// Minimal database pool interface; concrete impl behind compile flag.
class DbPool {
public:
    virtual ~DbPool() = default;
    virtual bool valid() const = 0;
    virtual bool ping(std::string* err = nullptr) = 0;

    static std::shared_ptr<DbPool> create(const AppConfigPayload::DatabaseConfig& cfg);
};

} // namespace va::storage

