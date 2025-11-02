#include "server/rest_impl.hpp"
#include "analyzer/model_registry.hpp"
#include "core/wal.hpp"
#include "utils/cuda_ctx_guard.hpp"
#include "exec/gpu_executor.hpp"
#include <future>

namespace va::server {

namespace {
// 失败原因归一：根据错误文本关键字映射到标准码
std::string normalize_reason(const std::string& err, const std::string& fallback) {
    std::string s = toLower(err);
    if (s.find("acl") != std::string::npos && s.find("scheme") != std::string::npos) return "acl_scheme";
    if (s.find("acl") != std::string::npos && s.find("profile") != std::string::npos) return "acl_profile";
    if ((s.find("open") != std::string::npos || s.find("connect") != std::string::npos || s.find("rtsp") != std::string::npos)) return "open_rtsp_failed";
    if (s.find("model") != std::string::npos || s.find("load") != std::string::npos) return "load_model_failed";
    if (s.find("start") != std::string::npos || s.find("pipeline") != std::string::npos) return "start_pipeline_failed";
    if (s.find("subscribe") != std::string::npos) return "subscribe_failed";
    return fallback;
}
} // anonymous

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
    // Legacy SubscriptionManager removed; use LRO Runner + Admission
    // 1) 读取 YAML 配置
    const auto& cfg = app.appConfig().subscriptions;
    int hs = cfg.heavy_slots > 0 ? cfg.heavy_slots : 2;     subs_src_heavy = (cfg.heavy_slots > 0 ? "config" : "defaults");
    int ms = cfg.model_slots > 0 ? cfg.model_slots : 2;     subs_src_model = (cfg.model_slots > 0 ? "config" : "defaults");
    int rs = cfg.rtsp_slots  > 0 ? cfg.rtsp_slots  : 4;     subs_src_rtsp  = (cfg.rtsp_slots  > 0 ? "config" : "defaults");
    int open = cfg.open_rtsp_slots >= 0 ? cfg.open_rtsp_slots : 0; subs_src_open_rtsp = (cfg.open_rtsp_slots >= 0 ? "config" : "defaults");
    int start = cfg.start_pipeline_slots >= 0 ? cfg.start_pipeline_slots : 0; subs_src_start_pipeline = (cfg.start_pipeline_slots >= 0 ? "config" : "defaults");
    if (cfg.load_model_slots > 0) { ms = cfg.load_model_slots; subs_src_model = "config"; }
    size_t mq = cfg.max_queue > 0 ? cfg.max_queue : 1024;   subs_src_queue = (cfg.max_queue  > 0 ? "config" : "defaults");
    int ttl = cfg.ttl_seconds > 0 ? cfg.ttl_seconds : 900;  subs_src_ttl   = (cfg.ttl_seconds> 0 ? "config" : "defaults");
    // 2) 环境变量覆盖（优先生效）
    auto hasEnv = [](const char* name) { return std::getenv(name) != nullptr; };
    auto envInt = [](const char* name, int fallback) { const char* v = std::getenv(name); if(!v) return fallback; try { return std::stoi(v); } catch(...) { return fallback; } };
    auto envSize = [](const char* name, size_t fallback) { const char* v = std::getenv(name); if(!v) return fallback; try { return static_cast<size_t>(std::stoll(v)); } catch(...) { return fallback; } };
    if (hasEnv("VA_SUBSCRIPTION_HEAVY_SLOTS")) { hs = envInt("VA_SUBSCRIPTION_HEAVY_SLOTS", hs); subs_src_heavy = "env"; }
    if (hasEnv("VA_SUBSCRIPTION_MODEL_SLOTS")) { ms = envInt("VA_SUBSCRIPTION_MODEL_SLOTS", ms); subs_src_model = "env"; }
    if (hasEnv("VA_SUBSCRIPTION_LOAD_MODEL_SLOTS")) { ms = envInt("VA_SUBSCRIPTION_LOAD_MODEL_SLOTS", ms); subs_src_model = "env"; }
    if (hasEnv("VA_SUBSCRIPTION_RTSP_SLOTS"))  { rs = envInt("VA_SUBSCRIPTION_RTSP_SLOTS", rs);  subs_src_rtsp  = "env"; }
    if (hasEnv("VA_SUBSCRIPTION_OPEN_RTSP_SLOTS"))  { open = envInt("VA_SUBSCRIPTION_OPEN_RTSP_SLOTS", open);  subs_src_open_rtsp  = "env"; }
    if (hasEnv("VA_SUBSCRIPTION_START_PIPELINE_SLOTS"))  { start = envInt("VA_SUBSCRIPTION_START_PIPELINE_SLOTS", start);  subs_src_start_pipeline  = "env"; }
    if (hasEnv("VA_SUBSCRIPTION_MAX_QUEUE"))   { mq = envSize("VA_SUBSCRIPTION_MAX_QUEUE", mq); subs_src_queue = "env"; }
    if (hasEnv("VA_SUBSCRIPTION_TTL_SEC"))     { ttl = envInt("VA_SUBSCRIPTION_TTL_SEC", ttl);  subs_src_ttl   = "env"; }
    // 3) 应用到订阅管理器
    cfg_heavy_slots_ = hs;
    cfg_model_slots_ = ms;
    cfg_rtsp_slots_ = rs;
    cfg_open_rtsp_slots_ = open;
    cfg_start_pipeline_slots_ = start;
    cfg_max_queue_ = mq;
    cfg_ttl_seconds_ = ttl;

    // Optional: initialize LRO runner when enabled
    try {
        const char* lro_env = std::getenv("VA_LRO_ENABLED");
        if (!lro_env) {
            // Default ON during transition: routed via provider bridge to legacy manager
            lro_enabled_ = true;
        } else {
            std::string v = lro_env; std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){ return (char)std::tolower(c); });
            lro_enabled_ = (v=="1"||v=="true"||v=="yes"||v=="on");
        }
        if (lro_enabled_) {
            lro_store_ = lro::make_memory_store();
            lro_admission_ = std::make_unique<lro::AdmissionPolicy>();
            lro::RunnerConfig rcfg; rcfg.store = lro_store_;
            lro_runner_ = std::make_unique<lro::Runner>(rcfg);
            // Attach minimal VA Steps: preparing -> starting_pipeline (subscribe) -> ready
            lro_runner_->addStep(lro::Step{"prepare", [this](std::shared_ptr<lro::Operation>& op){
                op->phase = "preparing";
            }, lro::Step::IO, 10});
            // opening_rtsp: minimal URI scheme validation
            lro_runner_->addStep(lro::Step{"opening_rtsp", [this](std::shared_ptr<lro::Operation>& op){
                op->phase = "opening_rtsp";
                try {
                    Json::Value sx = parseJson(op->spec_json);
                    std::string uri; if (sx.isMember("source_uri") && sx["source_uri"].isString()) uri = sx["source_uri"].asString();
                    if (sx.isMember("uri") && uri.empty() && sx["uri"].isString()) uri = sx["uri"].asString();
                    if (sx.isMember("url") && uri.empty() && sx["url"].isString()) uri = sx["url"].asString();
                    auto pos = uri.find(":"); std::string scheme = (pos==std::string::npos? std::string() : toLower(uri.substr(0,pos)));
                    if (scheme.rfind("rtsp", 0) != 0) { op->reason = "acl_scheme"; throw std::runtime_error("scheme_not_allowed"); }
                } catch (...) { if (op->phase != "failed") { op->status.store(lro::Status::Failed, std::memory_order_relaxed); op->phase = "failed"; } throw; }
            }, lro::Step::IO, 20});
            // loading_model: optional model load
            lro_runner_->addStep(lro::Step{"loading_model", [this](std::shared_ptr<lro::Operation>& op){
                op->phase = "loading_model";
                try {
                    Json::Value sx = parseJson(op->spec_json);
                    if (sx.isMember("model_id") && sx["model_id"].isString()) {
                        std::string mid = sx["model_id"].asString();
                        if (!mid.empty()) {
                            // Dispatch to GPU HookedExecutor to ensure CUDA context is initialized on worker threads.
                            std::exception_ptr ep;
                            std::promise<void> done;
                            bool submitted = va::exec::gpu_executor().trySubmit([&]{
                                try {
                                    if (!app.loadModel(mid)) {
                                        throw std::runtime_error("load_model_failed");
                                    }
                                } catch (...) {
                                    ep = std::current_exception();
                                }
                                try { done.set_value(); } catch (...) {}
                            });
                            if (!submitted) {
                                // fallback to synchronous execution on current thread with CUDA ensure
                                va::utils::ensure_cuda_ready(0);
                                if (!app.loadModel(mid)) { op->reason = normalize_reason(app.lastError(), "load_model_failed"); throw std::runtime_error("load_model_failed"); }
                            } else {
                                auto future = done.get_future();
                                future.wait();
                                if (ep) { std::rethrow_exception(ep); }
                            }
                            if (!app.isModelActive(mid)) {
                                op->reason = normalize_reason(app.lastError(), "load_model_failed");
                                throw std::runtime_error("load_model_failed");
                            }
                        }
                    }
                } catch (...) { if (op->phase != "failed") { op->status.store(lro::Status::Failed, std::memory_order_relaxed); op->phase = "failed"; } throw; }
            }, lro::Step::Heavy, 60});
            lro_runner_->addStep(lro::Step{"start_pipeline", [this](std::shared_ptr<lro::Operation>& op){
                try {
                    std::string stream_id, profile_id, uri; std::optional<std::string> model_override;
                    Json::Value sx = parseJson(op->spec_json);
                    if (sx.isMember("stream_id") && sx["stream_id"].isString()) stream_id = sx["stream_id"].asString();
                    if (sx.isMember("stream") && stream_id.empty() && sx["stream"].isString()) stream_id = sx["stream"].asString();
                    if (sx.isMember("profile") && sx["profile"].isString()) profile_id = sx["profile"].asString();
                    if (sx.isMember("profile_id") && profile_id.empty() && sx["profile_id"].isString()) profile_id = sx["profile_id"].asString();
                    if (sx.isMember("source_uri") && sx["source_uri"].isString()) uri = sx["source_uri"].asString();
                    if (sx.isMember("uri") && uri.empty() && sx["uri"].isString()) uri = sx["uri"].asString();
                    if (sx.isMember("url") && uri.empty() && sx["url"].isString()) uri = sx["url"].asString();
                    if (sx.isMember("model_id") && sx["model_id"].isString()) { auto v=sx["model_id"].asString(); if(!v.empty()) model_override=v; }
                    if (stream_id.empty() || profile_id.empty() || uri.empty()) { op->reason = "bad_request"; throw std::runtime_error("missing fields"); }
                    op->phase = "starting_pipeline";
                    auto key = app.subscribeStream(stream_id, profile_id, uri, model_override);
                    if (!key || key->empty()) { op->reason = normalize_reason(app.lastError(), "subscribe_failed"); op->status.store(lro::Status::Failed, std::memory_order_relaxed); op->phase = "failed"; throw std::runtime_error("subscribe_failed"); }
                    // mark ready for minimal semantics; real readiness is async
                    op->status.store(lro::Status::Ready, std::memory_order_relaxed);
                    op->phase = "ready";
                } catch (...) {
                    if (op->phase != "ready") { op->status.store(lro::Status::Failed, std::memory_order_relaxed); op->phase = "failed"; op->finished_at = std::chrono::system_clock::now(); }
                    throw;
                }
            }, lro::Step::Start, 80});
            // Admission buckets mirror current config (best-effort; capacity is stored in policy)
            lro_admission_->setBucketCapacity("open_rtsp", open);
            lro_admission_->setBucketCapacity("load_model", ms);
            lro_admission_->setBucketCapacity("start_pipeline", start);
        }
    } catch (...) { lro_enabled_ = false; }
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

