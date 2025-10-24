#include "server/subscription_manager.hpp"
#include "core/wal.hpp"
#include "core/reason_codes.hpp"

#include "app/application.hpp"

#include <algorithm>
#include <iomanip>
#include <random>
#include <sstream>

namespace va::server {

namespace {
bool isTerminalPhase(SubscriptionPhase phase) {
    switch (phase) {
    case SubscriptionPhase::Ready:
    case SubscriptionPhase::Failed:
    case SubscriptionPhase::Cancelled:
        return true;
    default:
        return false;
    }
}
} // namespace

SubscriptionManager::SubscriptionManager(va::app::Application& app)
    : app_(app) {
    // Best-effort：初始化 WAL（可选）
    try { va::core::wal::init(); } catch (...) {}
    const unsigned int worker_count = std::max(1u, std::thread::hardware_concurrency());
    for (unsigned int i = 0; i < worker_count; ++i) {
        workers_.emplace_back(&SubscriptionManager::workerLoop, this);
    }
    for (auto& c : hist_counts_) c.store(0);
    for (auto& c : hist_opening_counts_) c.store(0);
    for (auto& c : hist_loading_counts_) c.store(0);
    for (auto& c : hist_starting_counts_) c.store(0);
    cleaner_stop_.store(false, std::memory_order_relaxed);
    cleaner_ = std::thread(&SubscriptionManager::cleanerLoop, this);
}

SubscriptionManager::~SubscriptionManager() {
    {
        std::lock_guard<std::mutex> lk(mutex_);
        stop_ = true;
    }
    tasks_cv_.notify_all();
    cleaner_stop_.store(true, std::memory_order_relaxed);
    heavy_cv_.notify_all();
    model_cv_.notify_all();
    rtsp_cv_.notify_all();
    for (auto& t : workers_) {
        if (t.joinable()) {
            t.join();
        }
    }
    if (cleaner_.joinable()) cleaner_.join();
}

void SubscriptionManager::cleanerLoop() {
    // 定期清理达到 TTL 的终态任务，避免状态表无限增长
    using namespace std::chrono;
    const auto tick = seconds(5);
    while (!cleaner_stop_.load(std::memory_order_relaxed)) {
        std::this_thread::sleep_for(tick);
        int ttl = ttl_seconds_;
        if (ttl <= 0) continue;
        const auto now = system_clock::now();
        std::vector<std::string> to_erase;
        {
            std::lock_guard<std::mutex> lk(mutex_);
            for (const auto& kv : states_) {
                const auto& st = kv.second;
                if (!st) continue;
                auto ph = st->phase.load();
                if (!isTerminalPhase(ph)) continue;
                auto age = duration_cast<seconds>(now - st->created_at).count();
                if (age >= ttl) {
                    to_erase.push_back(kv.first);
                }
            }
            for (const auto& id : to_erase) {
                auto it = states_.find(id);
                if (it != states_.end()) {
                    const std::string key = it->second->request.stream_id + ":" + it->second->request.profile_id;
                    states_.erase(it);
                    auto ki = key_index_.find(key);
                    if (ki != key_index_.end() && ki->second == id) {
                        key_index_.erase(ki);
                    }
                }
            }
        }
    }
}

std::string SubscriptionManager::normalizeReason(const std::string& app_err, const char* fallback) {
    // 将后端错误消息归一化到有限集合，降低指标标签基数
    auto lower = [](std::string s){
        std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c){ return static_cast<char>(std::tolower(c)); });
        return s;
    };
    std::string s = lower(app_err);
    auto contains = [&](const char* k){ return s.find(k) != std::string::npos; };

    if (contains("timeout")) {
        if (contains("rtsp") || contains("connect") || contains("open")) return va::core::reasons::kOpenRtspTimeout;
        if (contains("model") || contains("onnx") || contains("session")) return va::core::reasons::kLoadModelTimeout;
    }
    if (contains("rtsp") && (contains("open") || contains("connect") || contains("teardown"))) return va::core::reasons::kOpenRtspFailed;
    if (contains("onnx") || contains("session") || contains("model")) return va::core::reasons::kLoadModelFailed;
    if (contains("pipeline") || contains("subscribe") || contains("start")) return va::core::reasons::kSubscribeFailed;
    if (contains("cancel")) return va::core::reasons::kCancelled;

    // Static table for common Application::last_error_ values
    if (contains("application not initialized"))   return va::core::reasons::kAppNotInitialized;
    if (contains("profile not found"))             return va::core::reasons::kProfileNotFound;
    if (contains("model not found"))               return va::core::reasons::kModelNotFound;
    if (contains("no model resolved"))             return va::core::reasons::kNoModelResolved;
    if (contains("pipeline initialization failed"))return va::core::reasons::kPipelineInitFailed;
    if (contains("failed to initialize pipeline for model")) return va::core::reasons::kPipelineInitModel;
    if (contains("failed to switch source"))       return va::core::reasons::kSwitchSourceFailed;
    if (contains("failed to switch model"))        return va::core::reasons::kSwitchModelFailed;
    if (contains("failed to switch task"))         return va::core::reasons::kSwitchTaskFailed;
    if (contains("failed to update analyzer params")) return va::core::reasons::kUpdateParamsFailed;
    if (contains("failed to set engine"))          return va::core::reasons::kSetEngineFailed;

    return (fallback && *fallback) ? std::string(fallback) : std::string(va::core::reasons::kUnknown);
}

void SubscriptionManager::setWhepBase(std::string whep_base_url) {
    std::lock_guard<std::mutex> lk(mutex_);
    whep_base_ = std::move(whep_base_url);
}

void SubscriptionManager::setMaxQueue(size_t n) {
    std::lock_guard<std::mutex> lk(mutex_);
    if (n == 0) return; // ignore invalid
    max_queue_ = n;
}

void SubscriptionManager::setHeavySlots(int n) {
    std::lock_guard<std::mutex> lk(heavy_mu_);
    if (n <= 0) return; // keep at least 1
    heavy_slots_ = n;
    heavy_cv_.notify_all();
}

size_t SubscriptionManager::maxQueue() const { return max_queue_; }
int SubscriptionManager::heavySlots() const { return heavy_slots_; }
void SubscriptionManager::setModelSlots(int n) {
    std::lock_guard<std::mutex> lk(model_mu_);
    if (n <= 0) return; model_slots_ = n; model_cv_.notify_all();
}
void SubscriptionManager::setRtspSlots(int n) {
    std::lock_guard<std::mutex> lk(rtsp_mu_);
    if (n <= 0) return; rtsp_slots_ = n; rtsp_cv_.notify_all();
}
int SubscriptionManager::modelSlots() const { return model_slots_; }
int SubscriptionManager::rtspSlots() const { return rtsp_slots_; }
// Optional per-phase slot setters/getters
void SubscriptionManager::setOpenRtspSlots(int n) {
    std::lock_guard<std::mutex> lk(open_mu_);
    // Allow 0 to disable gating; negative ignored
    if (n < 0) return;
    open_rtsp_slots_ = n;
    open_cv_.notify_all();
}

int SubscriptionManager::openRtspSlots() const {
    std::lock_guard<std::mutex> lk(open_mu_);
    return open_rtsp_slots_;
}

void SubscriptionManager::setStartPipelineSlots(int n) {
    std::lock_guard<std::mutex> lk(start_mu_);
    if (n < 0) return;
    start_slots_ = n;
    start_cv_.notify_all();
}

int SubscriptionManager::startPipelineSlots() const {
    std::lock_guard<std::mutex> lk(start_mu_);
    return start_slots_;
}
void SubscriptionManager::setTtlSeconds(int n) { if (n > 0) ttl_seconds_ = n; }
int SubscriptionManager::ttlSeconds() const { return ttl_seconds_; }

std::string SubscriptionManager::enqueue(const SubscriptionRequest& request, bool prefer_reuse_ready) {
    auto state = std::make_shared<SubscriptionState>();
    state->request = request;
    if (request.requester_key) state->requester_key = *request.requester_key;
    state->created_at = std::chrono::system_clock::now();
    // 记录 pending 时间（ms since epoch）
    state->ts_pending.store(static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(state->created_at.time_since_epoch()).count()), std::memory_order_relaxed);

    const std::string key = request.stream_id + ":" + request.profile_id;
    std::string id = nextId();

    {
        std::lock_guard<std::mutex> lk(mutex_);
        auto it = key_index_.find(key);
        if (it != key_index_.end()) {
            auto sit = states_.find(it->second);
            if (sit != states_.end()) {
                auto phase = sit->second->phase.load();
                // 如果仍在进行中，直接复用
                if (!isTerminalPhase(phase)) {
                    return it->second;
                }
                // 若已 Ready 且调用方要求优先复用，则直接返回现有订阅 ID
                if (prefer_reuse_ready && phase == SubscriptionPhase::Ready) {
                    return it->second;
                }
            }
        }
        // 简易过载保护：当挂起任务过多时拒绝新入队
        if (pending_.size() >= max_queue_) {
            throw std::runtime_error("queue_full");
        }
        states_[id] = state;
        key_index_[key] = id;
        pending_.push(Task{id, state});
    }
    // WAL：记录入队（最小充分）
    try {
        va::core::wal::append_subscription_event(
            "enqueue", id, key, "pending", std::string(),
            state->ts_pending.load(std::memory_order_relaxed),
            state->ts_preparing.load(std::memory_order_relaxed),
            state->ts_opening.load(std::memory_order_relaxed),
            state->ts_loading.load(std::memory_order_relaxed),
            state->ts_starting.load(std::memory_order_relaxed),
            state->ts_ready.load(std::memory_order_relaxed),
            state->ts_failed.load(std::memory_order_relaxed),
            state->ts_cancelled.load(std::memory_order_relaxed));
    } catch (...) {}

    tasks_cv_.notify_one();
    return id;
}

std::shared_ptr<SubscriptionState> SubscriptionManager::get(const std::string& id) const {
    std::lock_guard<std::mutex> lk(mutex_);
    auto it = states_.find(id);
    if (it == states_.end()) {
        return nullptr;
    }
    return it->second;
}

bool SubscriptionManager::cancel(const std::string& id) {
    auto state = get(id);
    if (!state) {
        return false;
    }
    state->cancel.store(true);
    auto phase = state->phase.load();
    if (isTerminalPhase(phase)) {
        if (!state->pipeline_key.empty()) {
            ensurePipelineStopped(state->request.stream_id, state->request.profile_id);
        }
        if (!state->metrics_recorded.load()) recordCompletion(state, phase);
        return true;
    }
    state->phase.store(SubscriptionPhase::Cancelled);
    state->reason = va::core::reasons::kCancelled;
    if (state->ts_cancelled.load(std::memory_order_relaxed) == 0) {
        auto now_ms = static_cast<std::uint64_t>(
            std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count());
        state->ts_cancelled.store(now_ms, std::memory_order_relaxed);
    }
    if (!state->pipeline_key.empty()) {
        ensurePipelineStopped(state->request.stream_id, state->request.profile_id);
    }
    recordCompletion(state, SubscriptionPhase::Cancelled);
    return true;
}

void SubscriptionManager::workerLoop() {
    for (;;) {
        Task task;
        {
            std::unique_lock<std::mutex> lk(mutex_);
            tasks_cv_.wait(lk, [this]() { return stop_ || !pending_.empty(); });
            if (stop_ && pending_.empty()) {
                return;
            }
            task = pending_.front();
            pending_.pop();
        }

        if (!task.state) {
            continue;
        }
        runSubscriptionTask(task.id, task.state);
    }
}

void SubscriptionManager::runSubscriptionTask(const std::string& /*id*/, const StatePtr& state) {
    if (!state) return;

    auto now_ms = [](){ return static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count()); };
    state->phase.store(SubscriptionPhase::Preparing);
    if (state->ts_preparing.load(std::memory_order_relaxed) == 0) state->ts_preparing.store(now_ms(), std::memory_order_relaxed);
    if (state->cancel.load()) {
        state->phase.store(SubscriptionPhase::Cancelled);
        state->reason = va::core::reasons::kCancelled;
        if (state->ts_cancelled.load(std::memory_order_relaxed) == 0) state->ts_cancelled.store(now_ms(), std::memory_order_relaxed);
        recordCompletion(state, SubscriptionPhase::Cancelled);
        return;
    }

    state->phase.store(SubscriptionPhase::OpeningRtsp);
    if (state->ts_opening.load(std::memory_order_relaxed) == 0) state->ts_opening.store(now_ms(), std::memory_order_relaxed);
    // 分阶段限流：OpeningRtsp（可选，0=未启用）
    bool got_open_slot = acquireOpenRtspSlot();
    struct OpenGuard { SubscriptionManager* m; bool a; ~OpenGuard(){ if(m&&a) m->releaseOpenRtspSlot(); } } og{this, got_open_slot};
    if (state->cancel.load()) {
        state->phase.store(SubscriptionPhase::Cancelled);
        state->reason = va::core::reasons::kCancelled;
        if (state->ts_cancelled.load(std::memory_order_relaxed) == 0) state->ts_cancelled.store(now_ms(), std::memory_order_relaxed);
        recordCompletion(state, SubscriptionPhase::Cancelled);
        return;
    }

    // 进入 LoadingModel 前释放 opening slot（提前释放并关闭 RAII）
    if (got_open_slot) { releaseOpenRtspSlot(); got_open_slot = false; og.a = false; }
    state->phase.store(SubscriptionPhase::LoadingModel);
    if (state->ts_loading.load(std::memory_order_relaxed) == 0) state->ts_loading.store(now_ms(), std::memory_order_relaxed);
    if (state->request.model_id) {
        bool got_model = acquireModelSlot();
        struct ModelGuard { SubscriptionManager* m; bool a; ~ModelGuard(){ if(m&&a) m->releaseModelSlot(); } } mg{this, got_model};
        if (!got_model) {
            state->phase.store(SubscriptionPhase::Failed);
            state->reason = va::core::reasons::kSubscribeFailed;
            if (state->ts_failed.load(std::memory_order_relaxed) == 0)
                state->ts_failed.store(now_ms(), std::memory_order_relaxed);
            recordCompletion(state, SubscriptionPhase::Failed);
            return;
        }
        if (!app_.loadModel(*state->request.model_id)) {
            state->phase.store(SubscriptionPhase::Failed);
            state->reason = normalizeReason(app_.lastError(), "load_model_failed");
            if (state->ts_failed.load(std::memory_order_relaxed) == 0) state->ts_failed.store(now_ms(), std::memory_order_relaxed);
            recordCompletion(state, SubscriptionPhase::Failed);
            return;
        }
    }

    if (state->cancel.load()) {
        state->phase.store(SubscriptionPhase::Cancelled);
        state->reason = va::core::reasons::kCancelled;
        if (state->ts_cancelled.load(std::memory_order_relaxed) == 0) state->ts_cancelled.store(now_ms(), std::memory_order_relaxed);
        recordCompletion(state, SubscriptionPhase::Cancelled);
        return;
    }

    state->phase.store(SubscriptionPhase::StartingPipeline);
    if (state->ts_starting.load(std::memory_order_relaxed) == 0) state->ts_starting.store(now_ms(), std::memory_order_relaxed);
    // 分阶段限流：优先使用 start_pipeline_slots；未设置则回退到 rtsp_slots
    bool use_start = (startPipelineSlots() > 0);
    bool got_start = use_start ? acquireStartSlot() : acquireRtspSlot();
    struct StartGuard { SubscriptionManager* m; bool use_start; bool a; ~StartGuard(){ if(!m) return; if (use_start){ if(a) m->releaseStartSlot(); } else { if(a) m->releaseRtspSlot(); } } } sg{this, use_start, got_start};
    auto pipeline_key = got_start ? app_.subscribeStream(state->request.stream_id,
                                             state->request.profile_id,
                                             state->request.source_uri,
                                             state->request.model_id)
                                  : std::optional<std::string>();
    if (!pipeline_key) {
        state->phase.store(SubscriptionPhase::Failed);
        state->reason = normalizeReason(app_.lastError(), "subscribe_failed");
        if (state->ts_failed.load(std::memory_order_relaxed) == 0) state->ts_failed.store(now_ms(), std::memory_order_relaxed);
        recordCompletion(state, SubscriptionPhase::Failed);
        return;
    }

    state->pipeline_key = *pipeline_key;
    std::string base;
    {
        std::lock_guard<std::mutex> lk(mutex_);
        base = whep_base_;
    }
    if (!base.empty()) {
        if (base.back() == '/') base.pop_back();
        state->whep_url = base + "/whep?stream=" + state->request.stream_id + ":" + state->request.profile_id;
    }

    if (state->cancel.load()) {
        ensurePipelineStopped(state->request.stream_id, state->request.profile_id);
        state->phase.store(SubscriptionPhase::Cancelled);
        state->reason = va::core::reasons::kCancelled;
        if (state->ts_cancelled.load(std::memory_order_relaxed) == 0) state->ts_cancelled.store(now_ms(), std::memory_order_relaxed);
        recordCompletion(state, SubscriptionPhase::Cancelled);
        return;
    }

    state->phase.store(SubscriptionPhase::Ready);
    if (state->ts_ready.load(std::memory_order_relaxed) == 0) state->ts_ready.store(now_ms(), std::memory_order_relaxed);
    recordCompletion(state, SubscriptionPhase::Ready);
}

std::string SubscriptionManager::nextId() {
    static std::atomic<uint64_t> counter{1};
    static thread_local std::mt19937_64 rng{std::random_device{}()};
    const uint64_t c = counter.fetch_add(1, std::memory_order_relaxed);
    std::uniform_int_distribution<uint64_t> dist;
    uint64_t r = dist(rng);

    std::ostringstream oss;
    oss << std::hex << std::setw(8) << std::setfill('0') << c
        << std::hex << std::setw(8) << std::setfill('0') << (r & 0xffffffffULL);
    return oss.str();
}

bool SubscriptionManager::acquireHeavySlot() {
    std::unique_lock<std::mutex> lk(heavy_mu_);
    heavy_cv_.wait(lk, [this]() { return stop_ || heavy_in_use_ < heavy_slots_; });
    if (stop_) return false;
    ++heavy_in_use_;
    return true;
}

void SubscriptionManager::releaseHeavySlot() {
    std::lock_guard<std::mutex> lk(heavy_mu_);
    if (heavy_in_use_ > 0) {
        --heavy_in_use_;
    }
    heavy_cv_.notify_one();
}

bool SubscriptionManager::acquireModelSlot() {
    std::unique_lock<std::mutex> lk(model_mu_);
    model_cv_.wait(lk, [this]() { return stop_ || model_in_use_ < model_slots_; });
    if (stop_) return false;
    ++model_in_use_;
    return true;
}
void SubscriptionManager::releaseModelSlot() {
    std::lock_guard<std::mutex> lk(model_mu_);
    if (model_in_use_ > 0) --model_in_use_;
    model_cv_.notify_one();
}
bool SubscriptionManager::acquireRtspSlot() {
    std::unique_lock<std::mutex> lk(rtsp_mu_);
    rtsp_cv_.wait(lk, [this]() { return stop_ || rtsp_in_use_ < rtsp_slots_; });
    if (stop_) return false;
    ++rtsp_in_use_;
    return true;
}
void SubscriptionManager::releaseRtspSlot() {
    std::lock_guard<std::mutex> lk(rtsp_mu_);
    if (rtsp_in_use_ > 0) --rtsp_in_use_;
    rtsp_cv_.notify_one();
}
bool SubscriptionManager::acquireOpenRtspSlot() {
    std::unique_lock<std::mutex> lk(open_mu_);
    // Disabled when not configured (>0 means enabled gating)
    if (open_rtsp_slots_ <= 0) return false;
    open_cv_.wait(lk, [this]() { return stop_ || open_in_use_ < open_rtsp_slots_; });
    if (stop_) return false;
    ++open_in_use_;
    return true;
}

void SubscriptionManager::releaseOpenRtspSlot() {
    std::lock_guard<std::mutex> lk(open_mu_);
    if (open_in_use_ > 0) --open_in_use_;
    open_cv_.notify_one();
}

bool SubscriptionManager::acquireStartSlot() {
    std::unique_lock<std::mutex> lk(start_mu_);
    if (start_slots_ <= 0) return false;
    start_cv_.wait(lk, [this]() { return stop_ || start_in_use_ < start_slots_; });
    if (stop_) return false;
    ++start_in_use_;
    return true;
}

void SubscriptionManager::releaseStartSlot() {
    std::lock_guard<std::mutex> lk(start_mu_);
    if (start_in_use_ > 0) --start_in_use_;
    start_cv_.notify_one();
}

bool SubscriptionManager::ensurePipelineStopped(const std::string& stream_id, const std::string& profile_id) {
    try {
        return app_.unsubscribeStream(stream_id, profile_id);
    } catch (...) {
        return false;
    }
}

const char* toString(SubscriptionPhase phase) {
    switch (phase) {
    case SubscriptionPhase::Pending:
        return "pending";
    case SubscriptionPhase::Preparing:
        return "preparing";
    case SubscriptionPhase::OpeningRtsp:
        return "opening_rtsp";
    case SubscriptionPhase::LoadingModel:
        return "loading_model";
    case SubscriptionPhase::StartingPipeline:
        return "starting_pipeline";
    case SubscriptionPhase::Ready:
        return "ready";
    case SubscriptionPhase::Failed:
        return "failed";
    case SubscriptionPhase::Cancelled:
        return "cancelled";
    default:
        return "unknown";
    }
}

void SubscriptionManager::recordCompletion(const StatePtr& state, SubscriptionPhase phase) {
    if (!state) return;
    bool expected = false;
    if (!state->metrics_recorded.compare_exchange_strong(expected, true)) {
        return; // already recorded
    }
    const auto now = std::chrono::system_clock::now();
    const auto dur = now - state->created_at;
    const double sec = std::chrono::duration<double>(dur).count();
    const long long usec = std::chrono::duration_cast<std::chrono::microseconds>(dur).count();
    // histogram
    for (size_t i = 0; i < hist_bounds_.size(); ++i) {
        if (sec <= hist_bounds_[i]) { hist_counts_[i].fetch_add(1, std::memory_order_relaxed); break; }
        if (i == hist_bounds_.size() - 1) { hist_counts_[i].fetch_add(1, std::memory_order_relaxed); }
    }
    hist_sum_us_.fetch_add(usec, std::memory_order_relaxed);
    hist_count_.fetch_add(1, std::memory_order_relaxed);

    // per-phase durations using timeline if available
    auto bump_hist = [&](double dsec, std::array<std::atomic<uint64_t>,6>& buckets,
                         std::atomic<long long>& sum_us, std::atomic<uint64_t>& cnt){
        if (dsec <= 0.0 || !std::isfinite(dsec)) return;
        for (size_t i=0;i<hist_bounds_.size();++i) {
            if (dsec <= hist_bounds_[i]) { buckets[i].fetch_add(1, std::memory_order_relaxed); break; }
            if (i == hist_bounds_.size()-1) { buckets[i].fetch_add(1, std::memory_order_relaxed); }
        }
        long long us = static_cast<long long>(dsec * 1e6);
        sum_us.fetch_add(us, std::memory_order_relaxed);
        cnt.fetch_add(1, std::memory_order_relaxed);
    };
    auto ts = [&](std::atomic<std::uint64_t>& a){ return a.load(std::memory_order_relaxed); };
    const uint64_t t_open = ts(state->ts_opening);
    const uint64_t t_load = ts(state->ts_loading);
    const uint64_t t_start= ts(state->ts_starting);
    const uint64_t t_ready= ts(state->ts_ready);
    const uint64_t t_fail = ts(state->ts_failed);
    const uint64_t t_cancel = ts(state->ts_cancelled);
    auto pick_end = [&](uint64_t a, uint64_t b, uint64_t c){ return a>0? a : (b>0? b : (c>0? c : 0)); };
    const uint64_t end_open = pick_end(t_load, t_start, (phase==SubscriptionPhase::Ready? t_ready : (phase==SubscriptionPhase::Failed? t_fail : t_cancel)));
    const uint64_t end_load = pick_end(t_start, (phase==SubscriptionPhase::Ready? t_ready : (phase==SubscriptionPhase::Failed? t_fail : t_cancel)), 0);
    const uint64_t end_start= (phase==SubscriptionPhase::Ready? t_ready : (phase==SubscriptionPhase::Failed? t_fail : t_cancel));
    if (t_open>0 && end_open>t_open) bump_hist((end_open - t_open)/1000.0, hist_opening_counts_, hist_opening_sum_us_, hist_opening_count_);
    if (t_load>0 && end_load>t_load) bump_hist((end_load - t_load)/1000.0, hist_loading_counts_, hist_loading_sum_us_, hist_loading_count_);
    if (t_start>0 && end_start>t_start) bump_hist((end_start - t_start)/1000.0, hist_starting_counts_, hist_starting_sum_us_, hist_starting_count_);

    switch (phase) {
    case SubscriptionPhase::Ready:
        completed_ready_total_.fetch_add(1, std::memory_order_relaxed);
        break;
    case SubscriptionPhase::Failed: {
        completed_failed_total_.fetch_add(1, std::memory_order_relaxed);
        std::string r = state->reason.empty()? std::string("unknown") : state->reason;
        if (r.size() > 64) r.resize(64);
        std::lock_guard<std::mutex> lk(reasons_mu_);
        auto it = failed_reasons_.find(r);
        if (it == failed_reasons_.end()) it = failed_reasons_.emplace(r, 0).first;
        it->second.fetch_add(1, std::memory_order_relaxed);
        break;
    }
    case SubscriptionPhase::Cancelled:
        completed_cancelled_total_.fetch_add(1, std::memory_order_relaxed);
        break;
    default: break; }

    // WAL：记录完成态（ready/failed/cancelled）
    try {
        const std::string key = state->request.stream_id + ":" + state->request.profile_id;
        std::string ph = toString(phase);
        const std::string reason_code = state->reason;
        va::core::wal::append_subscription_event(
            ph, /*sub_id*/ state->pipeline_key.empty() ? std::string() : state->pipeline_key, key, ph, reason_code,
            state->ts_pending.load(std::memory_order_relaxed),
            state->ts_preparing.load(std::memory_order_relaxed),
            state->ts_opening.load(std::memory_order_relaxed),
            state->ts_loading.load(std::memory_order_relaxed),
            state->ts_starting.load(std::memory_order_relaxed),
            state->ts_ready.load(std::memory_order_relaxed),
            state->ts_failed.load(std::memory_order_relaxed),
            state->ts_cancelled.load(std::memory_order_relaxed));
    } catch (...) {}
}

SubscriptionManager::MetricsSnapshot SubscriptionManager::metricsSnapshot() const {
    MetricsSnapshot s;
    // queue length
    {
        std::lock_guard<std::mutex> lk(mutex_);
        s.queue_length = pending_.size();
        for (const auto& kv : states_) {
            auto ph = kv.second->phase.load();
            switch (ph) {
            case SubscriptionPhase::Pending: s.pending++; break;
            case SubscriptionPhase::Preparing: s.preparing++; break;
            case SubscriptionPhase::OpeningRtsp: s.opening++; break;
            case SubscriptionPhase::LoadingModel: s.loading++; break;
            case SubscriptionPhase::StartingPipeline: s.starting++; break;
            case SubscriptionPhase::Ready: s.ready++; break;
            case SubscriptionPhase::Failed: s.failed++; break;
            case SubscriptionPhase::Cancelled: s.cancelled++; break;
            }
        }
    }
    s.in_progress = s.pending + s.preparing + s.opening + s.loading + s.starting;
    s.completed_ready_total = completed_ready_total_.load();
    s.completed_failed_total = completed_failed_total_.load();
    s.completed_cancelled_total = completed_cancelled_total_.load();
    // histogram snapshot
    s.bounds.assign(hist_bounds_.begin(), hist_bounds_.end());
    s.bucket_counts.resize(hist_counts_.size());
    for (size_t i=0;i<hist_counts_.size();++i) s.bucket_counts[i] = hist_counts_[i].load();
    s.duration_sum = static_cast<double>(hist_sum_us_.load()) / 1e6;
    s.duration_count = hist_count_.load();
    // per-phase
    s.opening_bucket_counts.resize(hist_opening_counts_.size());
    s.loading_bucket_counts.resize(hist_loading_counts_.size());
    s.starting_bucket_counts.resize(hist_starting_counts_.size());
    for (size_t i=0;i<hist_opening_counts_.size();++i) s.opening_bucket_counts[i] = hist_opening_counts_[i].load();
    for (size_t i=0;i<hist_loading_counts_.size();++i) s.loading_bucket_counts[i] = hist_loading_counts_[i].load();
    for (size_t i=0;i<hist_starting_counts_.size();++i) s.starting_bucket_counts[i] = hist_starting_counts_[i].load();
    s.opening_duration_sum = static_cast<double>(hist_opening_sum_us_.load()) / 1e6;
    s.opening_duration_count = hist_opening_count_.load();
    s.loading_duration_sum = static_cast<double>(hist_loading_sum_us_.load()) / 1e6;
    s.loading_duration_count = hist_loading_count_.load();
    s.starting_duration_sum = static_cast<double>(hist_starting_sum_us_.load()) / 1e6;
    s.starting_duration_count = hist_starting_count_.load();
    // failed reasons snapshot
    {
        std::lock_guard<std::mutex> lk(reasons_mu_);
        s.failed_by_reason.reserve(failed_reasons_.size());
        for (const auto& kv : failed_reasons_) {
            s.failed_by_reason.emplace_back(kv.first, kv.second.load());
        }
    }
    return s;
}

int SubscriptionManager::countInProgressByKey(const std::string& key) const {
    if (key.empty()) return 0;
    std::lock_guard<std::mutex> lk(mutex_);
    int n = 0;
    for (const auto& kv : states_) {
        auto ph = kv.second->phase.load();
        if (ph == SubscriptionPhase::Ready || ph == SubscriptionPhase::Failed || ph == SubscriptionPhase::Cancelled) continue;
        if (kv.second->requester_key == key) ++n;
    }
    return n;
}

} // namespace va::server
