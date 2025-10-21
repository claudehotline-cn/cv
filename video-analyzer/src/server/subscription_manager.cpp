#include "server/subscription_manager.hpp"

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
    const unsigned int worker_count = std::max(1u, std::thread::hardware_concurrency());
    for (unsigned int i = 0; i < worker_count; ++i) {
        workers_.emplace_back(&SubscriptionManager::workerLoop, this);
    }
    for (auto& c : hist_counts_) c.store(0);
}

SubscriptionManager::~SubscriptionManager() {
    {
        std::lock_guard<std::mutex> lk(mutex_);
        stop_ = true;
    }
    tasks_cv_.notify_all();
    heavy_cv_.notify_all();
    for (auto& t : workers_) {
        if (t.joinable()) {
            t.join();
        }
    }
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

std::string SubscriptionManager::enqueue(const SubscriptionRequest& request, bool prefer_reuse_ready) {
    auto state = std::make_shared<SubscriptionState>();
    state->request = request;
    state->created_at = std::chrono::system_clock::now();

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
    state->reason = "cancelled";
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

    state->phase.store(SubscriptionPhase::Preparing);
    if (state->cancel.load()) {
        state->phase.store(SubscriptionPhase::Cancelled);
        state->reason = "cancelled";
        return;
    }

    state->phase.store(SubscriptionPhase::OpeningRtsp);
    if (state->cancel.load()) {
        state->phase.store(SubscriptionPhase::Cancelled);
        state->reason = "cancelled";
        return;
    }

    state->phase.store(SubscriptionPhase::LoadingModel);
    if (state->request.model_id) {
        bool got_model = acquireModelSlot();
        struct ModelGuard { SubscriptionManager* m; bool a; ~ModelGuard(){ if(m&&a) m->releaseModelSlot(); } } mg{this, got_model};
        if (!got_model) {
            state->phase.store(SubscriptionPhase::Failed);
            state->reason = "shutdown";
            recordCompletion(state, SubscriptionPhase::Failed);
            return;
        }
        if (!app_.loadModel(*state->request.model_id)) {
            state->phase.store(SubscriptionPhase::Failed);
            state->reason = app_.lastError().empty() ? "load_model_failed" : app_.lastError();
            recordCompletion(state, SubscriptionPhase::Failed);
            return;
        }
    }

    if (state->cancel.load()) {
        state->phase.store(SubscriptionPhase::Cancelled);
        state->reason = "cancelled";
        return;
    }

    state->phase.store(SubscriptionPhase::StartingPipeline);
    bool got_rtsp = acquireRtspSlot();
    struct RtspGuard { SubscriptionManager* m; bool a; ~RtspGuard(){ if(m&&a) m->releaseRtspSlot(); } } rg{this, got_rtsp};
    auto pipeline_key = got_rtsp ? app_.subscribeStream(state->request.stream_id,
                                             state->request.profile_id,
                                             state->request.source_uri,
                                             state->request.model_id)
                                 : std::optional<std::string>();
    if (!pipeline_key) {
        state->phase.store(SubscriptionPhase::Failed);
        state->reason = app_.lastError().empty() ? "subscribe_failed" : app_.lastError();
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
        state->reason = "cancelled";
        recordCompletion(state, SubscriptionPhase::Cancelled);
        return;
    }

    state->phase.store(SubscriptionPhase::Ready);
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

} // namespace va::server
