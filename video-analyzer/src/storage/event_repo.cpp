#include "storage/event_repo.hpp"

namespace va::storage {

bool EventRepo::append(const std::vector<EventRow>& /*rows*/, std::string* err) {
    if (!pool_ || !pool_->valid()) { if (err) *err = "database disabled"; return false; }
    // Skeleton: to be implemented when MySQL is enabled
    if (err) *err = "not implemented";
    return false;
}

bool EventRepo::listRecent(const std::string& /*pipeline*/, const std::string& /*level*/, int /*limit*/, std::vector<EventRow>* out, std::string* err) {
    if (out) out->clear();
    if (!pool_ || !pool_->valid()) { if (err) *err = "database disabled"; return false; }
    if (err) *err = "not implemented";
    return false;
}

} // namespace va::storage

