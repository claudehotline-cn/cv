#pragma once
#include <atomic>

namespace va { namespace server {

extern std::atomic<int> g_sse_subscriptions_active;
extern std::atomic<int> g_sse_sources_active;
extern std::atomic<int> g_sse_logs_active;
extern std::atomic<int> g_sse_events_active;
extern std::atomic<unsigned long long> g_sse_reconnects_total;

} } // namespace va::server

