#include "lro/executors.h"

namespace lro {

BoundedExecutor::BoundedExecutor(size_t workers, size_t maxQueue)
    : maxQueue_(maxQueue) {
    for (size_t i = 0; i < workers; ++i) {
        workers_.emplace_back([this]{ worker(); });
    }
}

BoundedExecutor::~BoundedExecutor() { stop(); }

bool BoundedExecutor::trySubmit(std::function<void()> fn, std::chrono::milliseconds timeout) {
    std::unique_lock<std::mutex> lk(m_);
    if (!cvSpace_.wait_for(lk, timeout, [&]{ return q_.size() < maxQueue_ || stopping_.load(); })) return false;
    if (stopping_.load()) return false;
    q_.push(std::move(fn));
    cv_.notify_one();
    return true;
}

void BoundedExecutor::stop() {
    bool expected = false;
    if (!stopping_.compare_exchange_strong(expected, true)) return;
    cv_.notify_all();
    cvSpace_.notify_all();
    for (auto& t : workers_) if (t.joinable()) t.join();
}

void BoundedExecutor::worker() {
    while (!stopping_.load()) {
        std::function<void()> fn;
        {
            std::unique_lock<std::mutex> lk(m_);
            cv_.wait(lk, [&]{ return stopping_.load() || !q_.empty(); });
            if (stopping_.load()) break;
            fn = std::move(q_.front());
            q_.pop();
            cvSpace_.notify_one();
        }
        try { fn(); } catch (...) {}
    }
}

Executors& Executors::instance() { static Executors ex; return ex; }

} // namespace lro

