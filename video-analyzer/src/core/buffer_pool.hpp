#pragma once

#include <cstddef>
#include <memory>
#include <mutex>
#include <queue>

namespace va::core {

class HostBufferPool {
public:
    struct Memory {
        std::shared_ptr<void> owner;
        void* ptr {nullptr};
        std::size_t bytes {0};
    };

    explicit HostBufferPool(std::size_t block_bytes = 0, std::size_t capacity = 8)
        : block_bytes_(block_bytes), capacity_(capacity) {}

    // Acquire a buffer with at least 'bytes' capacity; may reinitialize pool block size.
    Memory acquire(std::size_t bytes);
    void release(Memory&& mem);

private:
    std::size_t block_bytes_ {0};
    std::size_t capacity_ {8};
    std::mutex mutex_;
    std::queue<std::shared_ptr<void>> free_;
};

} // namespace va::core

