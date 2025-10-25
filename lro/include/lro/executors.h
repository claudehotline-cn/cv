#pragma once
#include <queue>
#include <vector>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <functional>
#include <atomic>
#include <chrono>

namespace lro {

// 有界线程池（支持背压）
class BoundedExecutor {
public:
    BoundedExecutor(size_t workers, size_t maxQueue);
    ~BoundedExecutor();
    bool trySubmit(std::function<void()> fn, std::chrono::milliseconds timeout);
    void stop();
private:
    void worker();
    size_t maxQueue_;
    std::vector<std::thread> workers_;
    std::queue<std::function<void()>> q_;
    std::mutex m_;
    std::condition_variable cv_, cvSpace_;
    std::atomic<bool> stopping_{false};
};

struct Executors {
    BoundedExecutor io{2, 256};
    BoundedExecutor heavy{2, 64};
    BoundedExecutor start{2, 128};
    static Executors& instance();
};

} // namespace lro

