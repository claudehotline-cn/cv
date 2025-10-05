#include "core/buffer_pool.hpp"

#include <cstdlib>

namespace {

struct MallocDeleter {
    void operator()(void* p) const noexcept { std::free(p); }
};

static std::shared_ptr<void> make_host_block(std::size_t bytes) {
    if (bytes == 0) bytes = 1;
    void* p = std::malloc(bytes);
    if (!p) return {};
    return std::shared_ptr<void>(p, MallocDeleter{});
}

}

namespace va::core {

HostBufferPool::Memory HostBufferPool::acquire(std::size_t bytes) {
    Memory mem;
    if (bytes == 0) return mem;

    // If requested bigger than pool block, reinitialize pool sizing on demand
    if (block_bytes_ < bytes) {
        block_bytes_ = bytes;
        // drop existing free blocks; simplest reset
        std::lock_guard<std::mutex> lk(mutex_);
        while (!free_.empty()) free_.pop();
    }

    std::shared_ptr<void> owner;
    {
        std::lock_guard<std::mutex> lk(mutex_);
        if (!free_.empty()) { owner = std::move(free_.front()); free_.pop(); }
    }
    if (!owner) owner = make_host_block(block_bytes_);
    if (!owner) return mem;

    mem.owner = owner;
    mem.ptr = owner.get();
    mem.bytes = block_bytes_;
    return mem;
}

void HostBufferPool::release(Memory&& mem) {
    if (!mem.owner) return;
    std::lock_guard<std::mutex> lk(mutex_);
    if (free_.size() < capacity_) {
        free_.push(std::move(mem.owner));
    }
}

} // namespace va::core

