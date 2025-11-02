#pragma once

#include <vector>
#include <queue>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <functional>
#include <atomic>

namespace va { namespace exec {

struct ExecutorOptions {
    std::function<void()> thread_init; // per-thread init (e.g., CUDA context)
    std::function<void()> thread_fini; // per-thread fini
};

class HookedExecutor {
public:
    HookedExecutor(size_t workers, size_t maxQueue, ExecutorOptions opt)
        : maxQueue_(maxQueue), init_(std::move(opt.thread_init)), fini_(std::move(opt.thread_fini)) {
        for (size_t i = 0; i < workers; ++i) {
            workers_.emplace_back([this]{ this->worker(); });
        }
    }

    ~HookedExecutor() { stop(); }

    bool trySubmit(std::function<void()> fn) {
        std::unique_lock<std::mutex> lk(mu_);
        if (stopping_.load()) return false;
        if (q_.size() >= maxQueue_) return false;
        q_.push(std::move(fn));
        cv_.notify_one();
        return true;
    }

    void submit(std::function<void()> fn) {
        std::unique_lock<std::mutex> lk(mu_);
        cvSpace_.wait(lk, [&]{ return stopping_.load() || q_.size() < maxQueue_; });
        if (stopping_.load()) return;
        q_.push(std::move(fn));
        cv_.notify_one();
    }

    void stop() {
        bool expected = false;
        if (!stopping_.compare_exchange_strong(expected, true)) return;
        cv_.notify_all();
        cvSpace_.notify_all();
        for (auto& t : workers_) {
            if (t.joinable()) t.join();
        }
        workers_.clear();
    }

private:
    void worker() {
        if (init_) {
            try { init_(); } catch (...) {}
        }
        while (!stopping_.load()) {
            std::function<void()> fn;
            {
                std::unique_lock<std::mutex> lk(mu_);
                cv_.wait(lk, [&]{ return stopping_.load() || !q_.empty(); });
                if (stopping_.load()) break;
                fn = std::move(q_.front());
                q_.pop();
                cvSpace_.notify_one();
            }
            try { fn(); } catch (...) {}
        }
        if (fini_) {
            try { fini_(); } catch (...) {}
        }
    }

    size_t maxQueue_ {256};
    std::vector<std::thread> workers_;
    std::queue<std::function<void()>> q_;
    std::mutex mu_;
    std::condition_variable cv_;
    std::condition_variable cvSpace_;
    std::atomic<bool> stopping_{false};
    std::function<void()> init_;
    std::function<void()> fini_;
};

} } // namespace va::exec

