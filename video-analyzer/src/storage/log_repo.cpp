#include "storage/log_repo.hpp"

namespace va::storage {

bool LogRepo::append(const std::vector<LogRow>& /*rows*/, std::string* err) {
    if (!pool_ || !pool_->valid()) { if (err) *err = "database disabled"; return false; }
    if (err) *err = "not implemented";
    return false;
}

bool LogRepo::listRecent(const std::string& /*pipeline*/, const std::string& /*level*/, int /*limit*/, std::vector<LogRow>* out, std::string* err) {
    if (out) out->clear();
    if (!pool_ || !pool_->valid()) { if (err) *err = "database disabled"; return false; }
    if (err) *err = "not implemented";
    return false;
}

} // namespace va::storage

