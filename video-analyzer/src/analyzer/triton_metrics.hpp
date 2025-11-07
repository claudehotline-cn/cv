#pragma once

#include <vector>

namespace va { namespace analyzer { namespace metrics {

struct HistSnapshot;

void triton_record_rpc(double seconds, bool ok, const char* reason = nullptr);
HistSnapshot triton_snapshot_rpc();

} } }

