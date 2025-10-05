#pragma once

#include <cstddef>
#include <mutex>
#include <vector>

namespace va::core {

class GpuBufferPool {
public:
    struct Memory {
        void* ptr {nullptr};
        std::size_t bytes {0};
    };

    explicit GpuBufferPool(std::size_t block_bytes = 0, std::size_t capacity = 4);
    ~GpuBufferPool();

    Memory acquire(std::size_t bytes);
    void release(Memory&& mem);

private:
    std::size_t block_bytes_ {0};
    std::size_t capacity_ {4};
    std::mutex mutex_;
    std::vector<Memory> free_;
};

} // namespace va::core

