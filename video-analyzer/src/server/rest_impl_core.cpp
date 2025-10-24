#include "server/rest_impl.hpp"
#include "analyzer/model_registry.hpp"
#include "core/wal.hpp"

namespace va::server {

RestServer::Impl::Impl(RestServerOptions opts, va::app::Application& application)
    : options(std::move(opts)), app(application), server(options) {
    // WAL: init + mark restart + scan previous inflight (best-effort)
    try { va::core::wal::init(); va::core::wal::mark_restart(); va::core::wal::scanInflightBeforeLastRestart(); } catch (...) {}

    // Model registry: configure and start minimal preheat (best-effort)
    try {
        auto& mr = va::analyzer::ModelRegistry::instance();
        mr.configureFromEnv();
        mr.configurePreheatFromEnv();
        mr.setModels(app.detectionModels());
        mr.startPreheat();
    } catch (...) { /* ignore */ }
    subscriptions = std::make_unique<SubscriptionManager>(app);
    subscriptions->setWhepBase(app.appConfig().sfu_whep_base);
    // 1) 读取 YAML 配置
    const auto& cfg = app.appConfig().subscriptions;
    int hs = cfg.heavy_slots > 0 ? cfg.heavy_slots : 2;     subs_src_heavy = (cfg.heavy_slots > 0 ? "config" : "defaults");
    int ms = cfg.model_slots > 0 ? cfg.model_slots : 2;     subs_src_model = (cfg.model_slots > 0 ? "config" : "defaults");
    int rs = cfg.rtsp_slots  > 0 ? cfg.rtsp_slots  : 4;     subs_src_rtsp  = (cfg.rtsp_slots  > 0 ? "config" : "defaults");
    size_t mq = cfg.max_queue > 0 ? cfg.max_queue : 1024;   subs_src_queue = (cfg.max_queue  > 0 ? "config" : "defaults");
    int ttl = cfg.ttl_seconds > 0 ? cfg.ttl_seconds : 900;  subs_src_ttl   = (cfg.ttl_seconds> 0 ? "config" : "defaults");
    // 2) 环境变量覆盖（优先生效）
    auto hasEnv = [](const char* name) { return std::getenv(name) != nullptr; };
    auto envInt = [](const char* name, int fallback) { const char* v = std::getenv(name); if(!v) return fallback; try { return std::stoi(v); } catch(...) { return fallback; } };
    auto envSize = [](const char* name, size_t fallback) { const char* v = std::getenv(name); if(!v) return fallback; try { return static_cast<size_t>(std::stoll(v)); } catch(...) { return fallback; } };
    if (hasEnv("VA_SUBSCRIPTION_HEAVY_SLOTS")) { hs = envInt("VA_SUBSCRIPTION_HEAVY_SLOTS", hs); subs_src_heavy = "env"; }
    if (hasEnv("VA_SUBSCRIPTION_MODEL_SLOTS")) { ms = envInt("VA_SUBSCRIPTION_MODEL_SLOTS", ms); subs_src_model = "env"; }
    if (hasEnv("VA_SUBSCRIPTION_RTSP_SLOTS"))  { rs = envInt("VA_SUBSCRIPTION_RTSP_SLOTS", rs);  subs_src_rtsp  = "env"; }
    if (hasEnv("VA_SUBSCRIPTION_MAX_QUEUE"))   { mq = envSize("VA_SUBSCRIPTION_MAX_QUEUE", mq); subs_src_queue = "env"; }
    if (hasEnv("VA_SUBSCRIPTION_TTL_SEC"))     { ttl = envInt("VA_SUBSCRIPTION_TTL_SEC", ttl);  subs_src_ttl   = "env"; }
    // 3) 应用到订阅管理器
    subscriptions->setHeavySlots(hs);
    subscriptions->setModelSlots(ms);
    subscriptions->setRtspSlots(rs);
    subscriptions->setMaxQueue(mq);
    subscriptions->setTtlSeconds(ttl);
    // Initialize DB pool and repositories if configured
    try {
        const auto& dbc = app.appConfig().database;
        if (!dbc.driver.empty() && toLower(dbc.driver) == "mysql" && !dbc.host.empty() && dbc.port > 0) {
            db_pool = va::storage::DbPool::create(dbc);
            if (db_pool && db_pool->valid()) {
                logs_repo = std::make_unique<va::storage::LogRepo>(db_pool, dbc);
                events_repo = std::make_unique<va::storage::EventRepo>(db_pool, dbc);
                sessions_repo = std::make_unique<va::storage::SessionRepo>(db_pool, dbc);
                graphs_repo = std::make_unique<va::storage::GraphRepo>(db_pool, dbc);
                sources_repo = std::make_unique<va::storage::SourceRepo>(db_pool, dbc);
                startDbWorker();
                startRetentionWorker();
            }
        }
    } catch (...) {
        // Best-effort: keep server running even if DB init fails
    }
    registerRoutes();
}

RestServer::Impl::~Impl() { stopDbWorker(); stopRetentionWorker(); }

void RestServer::Impl::recordCpMetric(const std::string& op, int http_status, const std::chrono::steady_clock::time_point& t0) {
    auto t1 = std::chrono::steady_clock::now();
    double sec = std::chrono::duration<double>(t1 - t0).count();
    const char* code = va::core::errors::to_string(va::core::errors::from_http_status(http_status));
    std::lock_guard<std::mutex> lk(cp_mu);
    // totals
    cp_totals_by_code[op][code] += 1;
    // histogram
    auto& buckets = cp_hist_buckets[op];
    if (buckets.size() != cp_bounds.size()) buckets.assign(cp_bounds.size(), 0ULL);
    for (size_t i=0;i<cp_bounds.size();++i) {
        if (sec <= cp_bounds[i]) { buckets[i] += 1; break; }
        if (i == cp_bounds.size()-1) { buckets[i] += 1; }
    }
    cp_hist_sum[op] += sec;
    cp_hist_count[op] += 1;
}

std::uint64_t RestServer::Impl::now_ms() {
    using namespace std::chrono;
    return static_cast<std::uint64_t>(duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count());
}

void RestServer::Impl::startDbWorker() {
    if (!events_repo && !logs_repo) return;
    db_stop.store(false, std::memory_order_relaxed);
    db_thread = std::make_unique<std::thread>([this]() {
        const auto flush_interval = std::chrono::milliseconds(500);
        for (;;) {
            std::vector<va::storage::EventRow> evts;
            std::vector<va::storage::LogRow> logs;
            {
                std::unique_lock<std::mutex> lk(dbq_mutex);
                dbq_cv.wait_for(lk, flush_interval, [this]{ return db_stop.load(std::memory_order_relaxed) || !q_events.empty() || !q_logs.empty(); });
                if (db_stop.load(std::memory_order_relaxed) && q_events.empty() && q_logs.empty()) {
                    break;
                }
                evts.swap(q_events);
                logs.swap(q_logs);
            }
            if (!evts.empty() && events_repo) {
                std::string err; if (!events_repo->append(evts, &err)) {
                    VA_LOG_THROTTLED(::va::core::LogLevel::Error, "db", 5000) << "events append failed: " << err;
                }
            }
            if (!logs.empty() && logs_repo) {
                std::string err; if (!logs_repo->append(logs, &err)) {
                    VA_LOG_THROTTLED(::va::core::LogLevel::Error, "db", 5000) << "logs append failed: " << err;
                }
            }
        }
    });
}

void RestServer::Impl::stopDbWorker() {
    if (db_thread) {
        db_stop.store(true, std::memory_order_relaxed);
        dbq_cv.notify_all();
        if (db_thread->joinable()) db_thread->join();
        db_thread.reset();
    }
}

void RestServer::Impl::startRetentionWorker() {
    const auto& r = app.appConfig().database.retention;
    if (!r.enabled) return;
    if (r.interval_seconds <= 0) return;
    if (!events_repo && !logs_repo) return;
    retention_stop.store(false, std::memory_order_relaxed);
    retention_thread = std::make_unique<std::thread>([this]() {
        const auto& r = app.appConfig().database.retention;
        auto interval = std::chrono::seconds(r.interval_seconds > 0 ? r.interval_seconds : 600);
        // Add simple jitter to avoid thundering herd when multiple instances start at same time
        auto jitter_pct = (r.jitter_percent >= 0 && r.jitter_percent <= 100) ? r.jitter_percent : 10;
        auto jitter_ms = (interval.count() * jitter_pct / 100) * 1000;
        if (jitter_ms < 0) jitter_ms = 0;
        {
            // initial jittered delay
            int64_t delay_ms = (jitter_ms > 0) ? (std::rand() % (jitter_ms + 1)) : 0;
            if (delay_ms > 0) std::this_thread::sleep_for(std::chrono::milliseconds(delay_ms));
        }
        while (!retention_stop.load(std::memory_order_relaxed)) {
            const auto start = std::chrono::steady_clock::now();
            bool any_fail = false;
            if (events_repo && app.appConfig().database.retention.events_seconds > 0) {
                std::string err; if (events_repo->purgeOlderThanSeconds(app.appConfig().database.retention.events_seconds, &err)) {
                    VA_LOG_THROTTLED(::va::core::LogLevel::Info, "db.retention", 10000) << "events purge ok";
                } else if (!err.empty()) {
                    any_fail = true;
                    VA_LOG_THROTTLED(::va::core::LogLevel::Warn, "db.retention", 10000) << "events purge failed: " << err;
                }
            }
            if (logs_repo && app.appConfig().database.retention.logs_seconds > 0) {
                std::string err; if (logs_repo->purgeOlderThanSeconds(app.appConfig().database.retention.logs_seconds, &err)) {
                    VA_LOG_THROTTLED(::va::core::LogLevel::Info, "db.retention", 10000) << "logs purge ok";
                } else if (!err.empty()) {
                    any_fail = true;
                    VA_LOG_THROTTLED(::va::core::LogLevel::Warn, "db.retention", 10000) << "logs purge failed: " << err;
                }
            }
            auto dur_ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - start).count();
            retention_last_ms.store(static_cast<std::uint64_t>(dur_ms), std::memory_order_relaxed);
            retention_runs_total.fetch_add(1, std::memory_order_relaxed);
            if (any_fail) retention_failures_total.fetch_add(1, std::memory_order_relaxed);
            // sleep until next interval (with jitter each round)
            auto elapsed = std::chrono::steady_clock::now() - start;
            auto remaining = interval - std::chrono::duration_cast<std::chrono::seconds>(elapsed);
            if (remaining.count() < 1) remaining = std::chrono::seconds(1);
            // add jitter again
            int64_t delay_ms = (jitter_ms > 0) ? (std::rand() % (jitter_ms + 1)) : 0;
            std::this_thread::sleep_for(remaining + std::chrono::milliseconds(delay_ms));
        }
    });
}

void RestServer::Impl::stopRetentionWorker() {
    if (retention_thread) {
        retention_stop.store(true, std::memory_order_relaxed);
        if (retention_thread->joinable()) retention_thread->join();
        retention_thread.reset();
    }
}

void RestServer::Impl::emitEvent(const std::string& level,
                                 const std::string& type,
                                 const std::string& pipeline,
                                 const std::string& node,
                                 const std::string& stream_id,
                                 const std::string& msg,
                                 const std::string& extra_json) {
    if (!events_repo) return;
    va::storage::EventRow r;
    r.ts_ms = static_cast<std::int64_t>(now_ms());
    r.level = level; r.type = type; r.pipeline = pipeline; r.node = node; r.stream_id = stream_id; r.msg = msg; r.extra_json = extra_json;
    {
        std::lock_guard<std::mutex> lk(dbq_mutex);
        if (q_events.size() > 4096) q_events.clear();
        q_events.emplace_back(std::move(r));
    }
    dbq_cv.notify_one();
}

void RestServer::Impl::emitLog(const std::string& level,
                               const std::string& pipeline,
                               const std::string& node,
                               const std::string& stream_id,
                               const std::string& message,
                               const std::string& extra_json) {
    if (!logs_repo) return;
    va::storage::LogRow r;
    r.ts_ms = static_cast<std::int64_t>(now_ms());
    r.level = level; r.pipeline = pipeline; r.node = node; r.stream_id = stream_id; r.message = message; r.extra_json = extra_json;
    {
        std::lock_guard<std::mutex> lk(dbq_mutex);
        if (q_logs.size() > 4096) q_logs.clear();
        q_logs.emplace_back(std::move(r));
    }
    dbq_cv.notify_one();
}

bool RestServer::Impl::start() {
    return server.start();
}

void RestServer::Impl::stop() {
    server.stop();
}

RestServer::RestServer(RestServerOptions options, va::app::Application& app)
    : options_(std::move(options)), app_(app), impl_(std::make_unique<Impl>(options_, app_)) {}

RestServer::~RestServer() {
    stop();
}

bool RestServer::start() {
    return impl_ ? impl_->start() : false;
}

void RestServer::stop() {
    if (impl_) {
        impl_->stop();
    }
}

} // namespace va::server
