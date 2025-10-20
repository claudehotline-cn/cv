#pragma once

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <optional>
#include <queue>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

namespace va::app {
class Application;
}

namespace va::server {

enum class SubscriptionPhase {
    Pending,
    Preparing,
    OpeningRtsp,
    LoadingModel,
    StartingPipeline,
    Ready,
    Failed,
    Cancelled
};

struct SubscriptionRequest {
    std::string stream_id;
    std::string profile_id;
    std::string source_uri;
    std::optional<std::string> model_id;
};

struct SubscriptionState {
    std::atomic<SubscriptionPhase> phase{SubscriptionPhase::Pending};
    std::string reason;
    SubscriptionRequest request;
    std::string pipeline_key;
    std::string whep_url;
    std::atomic<bool> cancel{false};
    std::chrono::system_clock::time_point created_at{};
};

class SubscriptionManager {
public:
    explicit SubscriptionManager(va::app::Application& app);
    ~SubscriptionManager();

    std::string enqueue(const SubscriptionRequest& request);
    std::shared_ptr<SubscriptionState> get(const std::string& id) const;
    bool cancel(const std::string& id);
    void setWhepBase(std::string whep_base_url);

private:
    using StatePtr = std::shared_ptr<SubscriptionState>;

    struct Task {
        std::string id;
        StatePtr state;
    };
    struct HeavySlotGuard {
        SubscriptionManager* mgr;
        bool active;
        HeavySlotGuard(SubscriptionManager* m, bool a) : mgr(m), active(a) {}
        ~HeavySlotGuard() {
            if (mgr && active) mgr->releaseHeavySlot();
        }
    };

    void workerLoop();
    bool acquireHeavySlot();
    void releaseHeavySlot();
    void runSubscriptionTask(const std::string& id, const StatePtr& state);
    bool ensurePipelineStopped(const std::string& stream_id, const std::string& profile_id);
    std::string nextId();

    mutable std::mutex mutex_;
    std::unordered_map<std::string, StatePtr> states_;
    std::unordered_map<std::string, std::string> key_index_;
    std::queue<Task> pending_;
    mutable std::condition_variable tasks_cv_;
    std::vector<std::thread> workers_;
    bool stop_{false};

    va::app::Application& app_;
    std::string whep_base_;

    mutable std::mutex heavy_mu_;
    std::condition_variable heavy_cv_;
    int heavy_slots_{2};
    int heavy_in_use_{0};
};

const char* toString(SubscriptionPhase phase);

} // namespace va::server
