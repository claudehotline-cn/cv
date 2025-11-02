#include <cassert>
#include <chrono>
#include <iostream>
#include <memory>
#include <string>
#include <thread>

#include "lro/state_store.h"
#include "lro/runner.h"

using namespace std::chrono_literals;

static bool test_memory_store_basic() {
    auto store = lro::make_memory_store();
    auto op = std::make_shared<lro::Operation>();
    op->id = "op-1";
    op->idempotency_key = "key-1";
    op->status.store(lro::Status::Pending, std::memory_order_relaxed);
    if (!store->put(op)) return false;
    auto got = store->get("op-1");
    if (!got || got->id != "op-1") return false;
    auto bykey = store->getByKey("key-1");
    if (!bykey || bykey->id != "op-1") return false;
    op->status.store(lro::Status::Running, std::memory_order_relaxed);
    if (!store->update(op)) return false;
    auto got2 = store->get("op-1");
    if (!got2 || got2->status.load() != lro::Status::Running) return false;
    return true;
}

static bool test_runner_idempotency_and_cancel() {
    lro::RunnerConfig cfg; cfg.store = lro::make_memory_store();
    lro::Runner runner(cfg);
    // No steps: create() should quickly move to Ready
    const std::string spec = std::string("{\"stream_id\":\"s\",\"profile\":\"p\"}");
    auto id1 = runner.create(spec, "s:p");
    if (id1.empty()) return false;
    // Same idempotency key returns same id
    auto id2 = runner.create("{\"stream_id\":\"s\",\"profile\":\"p\",\"k\":1}", "s:p");
    if (id2 != id1) return false;
    // Poll ready
    bool ready = false;
    for (int i=0;i<50;i++) {
        auto op = runner.get(id1);
        if (op && op->status.load() == lro::Status::Ready) { ready = true; break; }
        std::this_thread::sleep_for(2ms);
    }
    if (!ready) return false;
    // Cancel after ready should be no-op true
    if (!runner.cancel(id1)) return false;
    return true;
}

int main() {
    bool ok = true;
    if (!test_memory_store_basic()) { std::cerr << "test_memory_store_basic failed\n"; ok = false; }
    if (!test_runner_idempotency_and_cancel()) { std::cerr << "test_runner_idempotency_and_cancel failed\n"; ok = false; }
    std::cout << (ok? "OK": "FAIL") << std::endl;
    return ok? 0 : 1;
}

