#pragma once
#include <vector>
#include <functional>
#include <memory>
#include <string>
#include <atomic>
#include <mutex>
#include <unordered_map>
#include <condition_variable>
#include <thread>
#include "lro/operation.h"
#include "lro/state_store.h"
#include "lro/executors.h"
#include "lro/notifier.h"
#include "lro/status.h"

namespace lro {

struct Step {
    std::string name;
    std::function<void(std::shared_ptr<Operation>&)> fn;
    enum Class { IO, Heavy, Start } clazz{IO};
    int progress_hint = 0; // 0-100
};

struct RunnerConfig {
    std::shared_ptr<IStateStore> store;
    INotifier* notifier = nullptr; // 可选
};

class Runner {
public:
    explicit Runner(RunnerConfig cfg) : cfg_(std::move(cfg)) {}

    void addStep(Step s) { steps_.push_back(std::move(s)); }

    // 幂等创建：若 idempotency_key 存在则复用
    std::string create(const std::string& spec_json, const std::string& idempotency_key) {
        if (!cfg_.store) cfg_.store = make_memory_store();
        if (auto ex = cfg_.store->getByKey(idempotency_key)) {
            return ex->id;
        }
        auto op = std::make_shared<Operation>();
        op->id = genId(idempotency_key);
        op->idempotency_key = idempotency_key;
        op->spec_json = spec_json;
        op->status.store(Status::Pending, std::memory_order_relaxed);
        op->phase = "pending";
        cfg_.store->put(op);
        // 提交执行：将步骤按类别分发到不同执行器
        submitPipeline(op);
        // 初次通知
        notify(op);
        return op->id;
    }

    std::shared_ptr<Operation> get(const std::string& id) {
        if (!cfg_.store) return {};
        return cfg_.store->get(id);
    }

    bool cancel(const std::string& id) {
        auto op = get(id);
        if (!op) return false;
        auto st = op->status.load(std::memory_order_relaxed);
        if (st == Status::Ready || st == Status::Failed || st == Status::Cancelled) return true;
        op->status.store(Status::Cancelled, std::memory_order_relaxed);
        op->phase = "cancelled";
        op->finished_at = std::chrono::system_clock::now();
        cfg_.store->update(op);
        notify(op);
        return true;
    }

    // 最简 watch：注册回调，立即回放一次当前快照（更多持久化/事件总线留给宿主）
    // One-shot watch (legacy behavior): invoke callback once with current snapshot
    void watch(const std::string& id, std::function<void(const std::shared_ptr<Operation>&)> cb) {
        if (!cb) return; cb(get(id));
    }

    struct WatchOptions { int interval_ms{200}; int keepalive_ms{10000}; };
    struct WatchHandle { std::atomic<bool> stop{false}; };
    // Continuous watch: spawn a lightweight polling loop that invokes cb on phase change
    // and periodically for keepalive; returns a handle to allow caller-driven stop.
    std::shared_ptr<WatchHandle> watch(const std::string& id,
                                       std::function<void(const std::shared_ptr<Operation>&)> cb,
                                       WatchOptions opts) {
        auto handle = std::make_shared<WatchHandle>();
        if (!cb) return handle;
        std::thread([this, id, cb, opts, handle]{
            std::string last;
            auto last_keep = std::chrono::steady_clock::now();
            while (!handle->stop.load(std::memory_order_relaxed)) {
                auto op = this->get(id);
                if (!op) { cb(op); return; }
                // initial or phase changed
                if (last.empty() || op->phase != last) { cb(op); last = op->phase; }
                // terminal -> exit
                auto st = op->status.load(std::memory_order_relaxed);
                if (st==Status::Ready || st==Status::Failed || st==Status::Cancelled) return;
                // keepalive
                auto now = std::chrono::steady_clock::now();
                if (std::chrono::duration_cast<std::chrono::milliseconds>(now - last_keep).count() >= opts.keepalive_ms) {
                    cb(op); last_keep = now;
                }
                std::this_thread::sleep_for(std::chrono::milliseconds(opts.interval_ms));
            }
        }).detach();
        return handle;
    }

    struct MetricsSnapshot {
        std::size_t queue_length{0};
        std::size_t in_progress{0};
        std::unordered_map<std::string, std::uint64_t> states;
        std::uint64_t completed_ready{0};
        std::uint64_t completed_failed{0};
        std::uint64_t completed_cancelled{0};
    };
    MetricsSnapshot metricsSnapshot() const {
        MetricsSnapshot ms;
        if (!cfg_.store) return ms;
        cfg_.store->for_each([&](const std::shared_ptr<Operation>& op){
            if (!op) return;
            auto st = op->status.load(std::memory_order_relaxed);
            const bool terminal = (st==Status::Ready || st==Status::Failed || st==Status::Cancelled);
            if (!terminal) ms.in_progress++;
            std::string ph = op->phase;
            if (ph.empty()) {
                switch (st) {
                    case Status::Pending: ph = "pending"; break;
                    case Status::Running: ph = "running"; break;
                    case Status::Ready: ph = "ready"; break;
                    case Status::Failed: ph = "failed"; break;
                    case Status::Cancelled: ph = "cancelled"; break;
                }
            }
            ms.states[ph] += 1;
            if (st == Status::Pending) ms.queue_length++;
            if (st == Status::Ready)     ms.completed_ready++;
            else if (st == Status::Failed)    ms.completed_failed++;
            else if (st == Status::Cancelled) ms.completed_cancelled++;
        });
        return ms;
    }

private:
    RunnerConfig cfg_;
    std::vector<Step> steps_;

    static std::string genId(const std::string& base_key) {
        static std::atomic<std::uint64_t> s{1};
        auto v = s.fetch_add(1, std::memory_order_relaxed);
        char buf[64];
        std::snprintf(buf, sizeof(buf), "%s-%llu", base_key.c_str(), static_cast<unsigned long long>(v));
        return std::string(buf);
    }

    void notify(const std::shared_ptr<Operation>& op) {
        if (!cfg_.notifier || !op) return;
        // 简化：仅回传 status 与 phase；宿主可自定义完整 JSON
        std::string payload = std::string("{\"status\":\"") + to_string(op->status.load()) +
                              "\",\"phase\":\"" + op->phase + "\"}";
        try { cfg_.notifier->notify(op->id, payload); } catch (...) {}
    }

    void submitPipeline(const std::shared_ptr<Operation>& op) {
        if (steps_.empty()) {
            // 无步骤：直接 Ready
            op->status.store(Status::Ready, std::memory_order_relaxed);
            op->phase = "ready";
            cfg_.store->update(op);
            notify(op);
            return;
        }
        // 标记 Running
        op->status.store(Status::Running, std::memory_order_relaxed);
        op->phase = "running";
        cfg_.store->update(op);
        notify(op);

        // 顺序执行各 Step；不同类别落在不同执行器
        std::shared_ptr<Operation> cur = op;
        for (auto& step : steps_) {
            auto task = [this, cur, step]() mutable {
                try {
                    if (step.progress_hint > 0) cur->progress.store(step.progress_hint, std::memory_order_relaxed);
                    step.fn(const_cast<std::shared_ptr<Operation>&>(cur));
                    cfg_.store->update(cur);
                    notify(cur);
                } catch (...) {
                    cur->status.store(Status::Failed, std::memory_order_relaxed);
                    cur->phase = "failed";
                    cur->finished_at = std::chrono::system_clock::now();
                    cfg_.store->update(cur);
                    notify(cur);
                }
            };
            auto& ex = pick(step.clazz);
            // 简化：不等待队列空位，直接尝试投递；失败则同步执行避免丢失
            if (!ex.trySubmit(task, std::chrono::milliseconds(10))) {
                task();
            }
        }
        // 最后一个 Step 完成后：置 Ready（若未失败/取消）
        auto finTask = [this, cur]() mutable {
            auto st = cur->status.load(std::memory_order_relaxed);
            if (st != Status::Failed && st != Status::Cancelled) {
                cur->status.store(Status::Ready, std::memory_order_relaxed);
                cur->phase = "ready";
                cur->finished_at = std::chrono::system_clock::now();
                cfg_.store->update(cur);
                notify(cur);
            }
        };
        pick(Step::Class::Start).trySubmit(finTask, std::chrono::milliseconds(10));
    }

    static BoundedExecutor& pick(Step::Class c) {
        auto& ex = Executors::instance();
        switch (c) {
            case Step::Class::IO:    return ex.io;
            case Step::Class::Heavy: return ex.heavy;
            case Step::Class::Start: return ex.start;
        }
        return ex.io;
    }
};

} // namespace lro
