#pragma once

#include "core/utils.hpp"

#include <cstddef>
#include <functional>
#include <memory>
#include <mutex>
#include <queue>

namespace va::core {

// Simple host buffer pool (pinned intent can be added later)
class HostBufferPool {
public:
    explicit HostBufferPool(std::size_t block_bytes, std::size_t capacity = 8, bool use_pinned = false)
        : block_bytes_(block_bytes), capacity_(capacity), use_pinned_(use_pinned) {}

    MemoryHandle acquire();
    void release(MemoryHandle&& handle);

private:
    std::size_t block_bytes_;
    std::size_t capacity_;
    bool use_pinned_;
    std::mutex mutex_;
    std::queue<std::shared_ptr<void>> free_;
};

// Placeholder for GPU buffer pool (device memory managed elsewhere)
class GpuBufferPool {
public:
    explicit GpuBufferPool(std::size_t block_bytes, std::size_t capacity = 8)
        : block_bytes_(block_bytes), capacity_(capacity) {}

    MemoryHandle acquire();
    void release(MemoryHandle&& handle);

private:
    std::size_t block_bytes_;
    std::size_t capacity_;
    std::mutex mutex_;
    std::queue<std::shared_ptr<void>> free_;
};

} // namespace va::core
