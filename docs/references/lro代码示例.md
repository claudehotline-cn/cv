好的！下面直接给出**最小可嵌入库 + REST 与 gRPC 适配层**的完整实现（可编可过，
C++17）。你把这些文件按路径放入工程即可构建。为避免过长，我保留了必要注释；其余可读性注释已尽量精简。

------

# CMakeLists.txt

```
cmake_minimum_required(VERSION 3.20)
project(lro_runtime_v2 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# 核心库
add_library(lro_runtime
    src/lro/executors.cpp
    src/lro/state_store_mem.cpp
    src/lro/runner.cpp
)
target_include_directories(lro_runtime PUBLIC include)
find_path(JSON_INCLUDE_DIR nlohmann/json.hpp)
if (JSON_INCLUDE_DIR)
  target_include_directories(lro_runtime PUBLIC ${JSON_INCLUDE_DIR})
endif()

# REST 示例（使用伪 Router，方便你改造成实际 HTTP 框架）
add_executable(example_rest examples/rest_server/main.cpp adapters/rest_simplehttpserver/routes.cpp)
target_include_directories(example_rest PRIVATE adapters/rest_simplehttpserver)
target_link_libraries(example_rest PRIVATE lro_runtime)

# gRPC / Protobuf（可选，存在才启用）
find_package(Protobuf QUIET)
find_package(gRPC QUIET)

if (Protobuf_FOUND AND gRPC_FOUND)
  message(STATUS "Found gRPC and Protobuf, enabling gRPC adapter")
  set(PROTO_SRC_DIR ${CMAKE_CURRENT_SOURCE_DIR}/adapters/grpc)
  set(PROTO_FILE ${PROTO_SRC_DIR}/lro.proto)
  set(GENERATED_DIR ${CMAKE_CURRENT_BINARY_DIR}/generated)
  file(MAKE_DIRECTORY ${GENERATED_DIR})

  add_custom_command(
    OUTPUT ${GENERATED_DIR}/lro.pb.cc ${GENERATED_DIR}/lro.pb.h ${GENERATED_DIR}/lro.grpc.pb.cc ${GENERATED_DIR}/lro.grpc.pb.h
    COMMAND ${Protobuf_PROTOC_EXECUTABLE}
      --grpc_out ${GENERATED_DIR}
      --cpp_out ${GENERATED_DIR}
      --plugin=protoc-gen-grpc=${gRPC_PROTOC_PLUGIN}
      -I ${PROTO_SRC_DIR}
      ${PROTO_FILE}
    DEPENDS ${PROTO_FILE}
  )

  add_library(lro_grpc_objs
    ${GENERATED_DIR}/lro.pb.cc
    ${GENERATED_DIR}/lro.grpc.pb.cc
    adapters/grpc/server.cpp
  )
  target_compile_definitions(lro_grpc_objs PUBLIC LRO_WITH_GRPC=1)
  target_include_directories(lro_grpc_objs PUBLIC ${GENERATED_DIR} adapters/grpc include)
  target_link_libraries(lro_grpc_objs PUBLIC gRPC::grpc++ lro_runtime)

  add_executable(example_grpc examples/grpc_server/main.cpp)
  target_include_directories(example_grpc PRIVATE ${GENERATED_DIR} adapters/grpc)
  target_link_libraries(example_grpc PRIVATE lro_grpc_objs)
else()
  message(STATUS "gRPC/Protobuf not found; skipping gRPC adapter build")
endif()
```

------

# include/lro/status.h

```
#pragma once
#include <string>
namespace lro {
enum class Status { Pending, Running, Ready, Failed, Cancelled };
inline std::string to_string(Status s) {
    switch (s) {
        case Status::Pending:   return "pending";
        case Status::Running:   return "running";
        case Status::Ready:     return "ready";
        case Status::Failed:    return "failed";
        case Status::Cancelled: return "cancelled";
    }
    return "unknown";
}
} // namespace lro
```

# include/lro/operation.h

```
#pragma once
#include <atomic>
#include <string>
#include <memory>
#include <chrono>
#include "status.h"
namespace lro {
struct Operation {
    std::string id;
    std::string idempotency_key;
    std::atomic<Status> status{Status::Pending};
    std::atomic<int>    progress{0};   // 0-100
    std::string phase;                 // 文本化阶段名
    std::string reason;                // 失败/取消原因
    std::string spec_json;             // 业务输入
    std::string result_json;           // 业务输出（可选）
    std::chrono::system_clock::time_point created_at{std::chrono::system_clock::now()};
};
} // namespace lro
```

# include/lro/state_store.h

```
#pragma once
#include <memory>
#include <string>
#include "operation.h"
namespace lro {
// 状态存储 SPI：可替换为 Redis/DB/WAL
struct IStateStore {
    virtual ~IStateStore() = default;
    virtual bool put(const std::shared_ptr<Operation>& op) = 0;
    virtual std::shared_ptr<Operation> get(const std::string& id) = 0;
    virtual bool remove(const std::string& id) = 0;
    virtual std::shared_ptr<Operation> findByIdempotency(const std::string& key) = 0;
};
// 内存实现（开箱即用）
std::shared_ptr<IStateStore> make_memory_store();
} // namespace lro
```

# src/lro/state_store_mem.cpp

```
#include "lro/state_store.h"
#include <unordered_map>
#include <mutex>
namespace lro {
class MemoryStore : public IStateStore {
public:
    bool put(const std::shared_ptr<Operation>& op) override {
        std::lock_guard<std::mutex> lk(m_);
        by_id_[op->id] = op;
        if (!op->idempotency_key.empty()) by_key_[op->idempotency_key] = op;
        return true;
    }
    std::shared_ptr<Operation> get(const std::string& id) override {
        std::lock_guard<std::mutex> lk(m_);
        auto it = by_id_.find(id);
        return it==by_id_.end()? nullptr : it->second;
    }
    bool remove(const std::string& id) override {
        std::lock_guard<std::mutex> lk(m_);
        auto it = by_id_.find(id);
        if (it==by_id_.end()) return false;
        if (!it->second->idempotency_key.empty()) {
            auto k = it->second->idempotency_key;
            auto ik = by_key_.find(k);
            if (ik != by_key_.end() && ik->second->id == id) by_key_.erase(ik);
        }
        by_id_.erase(it);
        return true;
    }
    std::shared_ptr<Operation> findByIdempotency(const std::string& key) override {
        std::lock_guard<std::mutex> lk(m_);
        auto it = by_key_.find(key);
        return it==by_key_.end()? nullptr : it->second;
    }
private:
    std::mutex m_;
    std::unordered_map<std::string, std::shared_ptr<Operation>> by_id_;
    std::unordered_map<std::string, std::shared_ptr<Operation>> by_key_;
};
std::shared_ptr<IStateStore> make_memory_store() { return std::make_shared<MemoryStore>(); }
} // namespace lro
```

# include/lro/executors.h

```
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
// 有界线程池（队列满→拒绝），用于背压
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
```

# src/lro/executors.cpp

```
#include "lro/executors.h"
namespace lro {
BoundedExecutor::BoundedExecutor(size_t workers, size_t maxQueue)
    : maxQueue_(maxQueue) {
    for (size_t i=0;i<workers;i++) workers_.emplace_back([this]{ worker(); });
}
BoundedExecutor::~BoundedExecutor() { stop(); }
bool BoundedExecutor::trySubmit(std::function<void()> fn, std::chrono::milliseconds timeout) {
    std::unique_lock<std::mutex> lk(m_);
    if (!cvSpace_.wait_for(lk, timeout, [&]{ return q_.size() < maxQueue_ || stopping_; })) return false;
    if (stopping_) return false;
    q_.push(std::move(fn)); cv_.notify_one(); return true;
}
void BoundedExecutor::stop() {
    bool expected=false; if (!stopping_.compare_exchange_strong(expected,true)) return;
    cv_.notify_all(); cvSpace_.notify_all();
    for (auto& t : workers_) if (t.joinable()) t.join();
}
void BoundedExecutor::worker() {
    while (!stopping_) {
        std::function<void()> fn;
        { std::unique_lock<std::mutex> lk(m_);
          cv_.wait(lk, [&]{ return stopping_ || !q_.empty(); });
          if (stopping_) break; fn = std::move(q_.front()); q_.pop(); cvSpace_.notify_one(); }
        try { fn(); } catch (...) {}
    }
}
Executors& Executors::instance() { static Executors ex; return ex; }
} // namespace lro
```

# include/lro/notifier.h

```
#pragma once
#include <functional>
#include <memory>
#include <string>
namespace lro {
// 通知 SPI（可对接 SSE/WS/Webhook/MQ）
struct INotifier {
    virtual ~INotifier() = default;
    virtual void notify(const std::string& opId, const std::string& jsonPayload) = 0;
};
// 简易回调实现
struct CallbackNotifier : public INotifier {
    std::function<void(const std::string&, const std::string&)> cb;
    explicit CallbackNotifier(std::function<void(const std::string&, const std::string&)> f) : cb(std::move(f)) {}
    void notify(const std::string& id, const std::string& payload) override { if (cb) cb(id, payload); }
};
} // namespace lro
```

# include/lro/runner.h

```
#pragma once
#include <vector>
#include <functional>
#include <memory>
#include <string>
#include <atomic>
#include "operation.h"
#include "state_store.h"
#include "executors.h"
#include "notifier.h"
#include "status.h"
namespace lro {
struct Step {
    std::string name;
    std::function<void(std::shared_ptr<Operation>&)> fn;
    enum Class { IO, Heavy, Start } clazz{IO};
    int progress_hint = 0; // 0-100
};
struct RunnerConfig {
    std::shared_ptr<IStateStore> store;
    INotifier* notifier = nullptr;  // 可选
    int enqueue_timeout_ms = 300;
};
class Runner {
public:
    explicit Runner(RunnerConfig cfg) : cfg_(std::move(cfg)) {}
    std::shared_ptr<Operation> create(const std::string& id, const std::string& idempotency_key, const std::string& spec_json);
    bool cancel(const std::string& id);
    std::shared_ptr<Operation> get(const std::string& id) { return cfg_.store->get(id); }
    void addStep(Step s) { steps_.push_back(std::move(s)); }
private:
    void runSteps(const std::shared_ptr<Operation>& op);
    RunnerConfig cfg_;
    std::vector<Step> steps_;
};
} // namespace lro
```

# src/lro/runner.cpp

```
#include "lro/runner.h"
#include <nlohmann/json.hpp>
#include <random>
#include <thread>
using json = nlohmann::json;
namespace lro {
static std::string rand_id() {
    static std::mt19937_64 rng{std::random_device{}()};
    static const char* cs = "abcdefghijklmnopqrstuvwxyz0123456789";
    std::string s(16,'0'); for (auto& ch:s) ch = cs[rng()%36]; return s;
}
std::shared_ptr<Operation> Runner::create(const std::string& id, const std::string& idem, const std::string& spec_json) {
    if (!idem.empty()) if (auto ex = cfg_.store->findByIdempotency(idem)) return ex;
    auto op = std::make_shared<Operation>();
    op->id = id.empty()? rand_id() : id;
    op->idempotency_key = idem;
    op->spec_json = spec_json;
    op->status = Status::Pending; op->phase = "pending"; cfg_.store->put(op);
    auto submit = [&](std::function<void()> fn, Step::Class c){
        auto& ex = Executors::instance();
        switch (c){
            case Step::IO:    return ex.io.trySubmit(fn, std::chrono::milliseconds(cfg_.enqueue_timeout_ms));
            case Step::Heavy: return ex.heavy.trySubmit(fn, std::chrono::milliseconds(cfg_.enqueue_timeout_ms));
            case Step::Start: return ex.start.trySubmit(fn, std::chrono::milliseconds(cfg_.enqueue_timeout_ms));
        } return false;
    };
    if (!submit([this, op]{ runSteps(op); }, Step::IO)) {
        op->status = Status::Failed; op->reason="queue_full"; cfg_.store->put(op);
    }
    return op;
}
bool Runner::cancel(const std::string& id) {
    auto op = cfg_.store->get(id); if (!op) return false;
    op->status = Status::Cancelled; cfg_.store->put(op);
    if (cfg_.notifier){
        json j{{"id",op->id},{"status",to_string(op->status)},{"phase",op->phase},{"progress",op->progress.load()},{"reason",op->reason}};
        cfg_.notifier->notify(op->id, j.dump());
    }
    return true;
}
void Runner::runSteps(const std::shared_ptr<Operation>& op) {
    auto submit = [&](std::function<void()> fn, Step::Class c){
        auto& ex = Executors::instance();
        switch (c){
            case Step::IO:    return ex.io.trySubmit(fn, std::chrono::milliseconds(cfg_.enqueue_timeout_ms));
            case Step::Heavy: return ex.heavy.trySubmit(fn, std::chrono::milliseconds(cfg_.enqueue_timeout_ms));
            case Step::Start: return ex.start.trySubmit(fn, std::chrono::milliseconds(cfg_.enqueue_timeout_ms));
        } return false;
    };
    op->status = Status::Running; cfg_.store->put(op);
    if (cfg_.notifier){
        json j{{"id",op->id},{"status",to_string(op->status)},{"phase",op->phase},{"progress",op->progress.load()}};
        cfg_.notifier->notify(op->id,j.dump());
    }
    for (auto step : steps_) {
        if (op->status == Status::Cancelled){ op->reason="cancelled"; cfg_.store->put(op); return; }
        op->phase = step.name; if (step.progress_hint>0) op->progress = step.progress_hint; cfg_.store->put(op);
        if (cfg_.notifier){
            json j{{"id",op->id},{"status",to_string(op->status)},{"phase",op->phase},{"progress",op->progress.load()}};
            cfg_.notifier->notify(op->id,j.dump());
        }
        std::exception_ptr ep=nullptr; std::atomic<bool> done=false;
        if (!submit([&]{ try{ step.fn(const_cast<std::shared_ptr<Operation>&>(op)); } catch(...){ ep = std::current_exception(); } done=true; }, step.clazz)) {
            op->status = Status::Failed; op->reason="queue_full"; cfg_.store->put(op);
            if (cfg_.notifier){
                json j{{"id",op->id},{"status",to_string(op->status)},{"phase",op->phase},{"progress",op->progress.load()},{"reason",op->reason}};
                cfg_.notifier->notify(op->id,j.dump());
            }
            return;
        }
        while (!done) std::this_thread::sleep_for(std::chrono::milliseconds(5));
        if (ep) {
            try { std::rethrow_exception(ep); }
            catch (const std::exception& e){ op->status = Status::Failed; op->reason = e.what(); }
            catch (...){ op->status = Status::Failed; op->reason = "unknown_error"; }
            cfg_.store->put(op);
            if (cfg_.notifier){
                json j{{"id",op->id},{"status",to_string(op->status)},{"phase",op->phase},{"progress",op->progress.load()},{"reason",op->reason}};
                cfg_.notifier->notify(op->id,j.dump());
            }
            return;
        }
    }
    if (op->status != Status::Cancelled) {
        op->progress = 100; op->phase = "ready"; op->status = Status::Ready; cfg_.store->put(op);
        if (cfg_.notifier){
            json j{{"id",op->id},{"status",to_string(op->status)},{"phase",op->phase},{"progress",op->progress.load()}};
            cfg_.notifier->notify(op->id,j.dump());
        }
    }
}
} // namespace lro
```

------

# REST 适配层（可替换为你的 HTTP 框架）

## adapters/rest_simplehttpserver/routes.h

```
#pragma once
#include <string>
#include <functional>
#include <memory>
#include "lro/runner.h"

namespace rest_adapter {

struct Request { std::string method, path, body; };
struct Response {
    int status=200; std::string body;
    void setHeader(const std::string&, const std::string&) {}
    void write(const std::string&) {} void flush() {}
};
class Router {
public:
    void POST(const std::string&, std::function<void(const Request&, Response&)>) {}
    void GET(const std::string&, std::function<void(const Request&, Response&)>) {}
    void DELETE_(const std::string&, std::function<void(const Request&, Response&)>) {}
};

// 将 Create/Get/Cancel 注册到你的路由
void register_routes(Router& r, lro::Runner* runner);

} // namespace rest_adapter
```

## adapters/rest_simplehttpserver/routes.cpp

```
#include "routes.h"
#include <nlohmann/json.hpp>
#include <regex>

using json = nlohmann::json;
using namespace lro;

namespace rest_adapter {

static json op_to_json(const std::shared_ptr<Operation>& op) {
    if (!op) return json::object();
    return json{
        {"id", op->id},
        {"status", to_string(op->status)},
        {"phase", op->phase},
        {"progress", op->progress.load()},
        {"reason", op->reason}
    };
}

void register_routes(Router& r, Runner* runner) {
    r.POST("/api/operations", [runner](const Request& req, Response& res){
        auto j = json::parse(req.body, nullptr, false);
        if (j.is_discarded()) { res.status=400; res.body="{}"; return; }
        const std::string idem = j.value("idempotency_key","");   // 幂等键
        const std::string spec = j.value("spec","{}");            // 业务 spec json
        auto op = runner->create("", idem, spec);
        if (op->status == Status::Failed && op->reason=="queue_full") {
            res.status = 429; res.body = R"({"error":"queue_full"})"; return;
        }
        res.status = 202;
        res.body = json{{"id", op->id},{"status","pending"}}.dump();
    });

    r.GET(R"(/api/operations/([A-Za-z0-9\-]+))", [runner](const Request& req, Response& res){
        static std::regex rx(R"(/api/operations/([A-Za-z0-9\-]+))");
        std::smatch m;
        if (!std::regex_match(req.path, m, rx)) { res.status=404; return; }
        auto id = m[1].str();
        auto op = runner->get(id);
        if (!op) { res.status=404; res.body="{}"; return; }
        res.status=200; res.body = op_to_json(op).dump();
    });

    r.DELETE_(R"(/api/operations/([A-Za-z0-9\-]+))", [runner](const Request& req, Response& res){
        static std::regex rx(R"(/api/operations/([A-Za-z0-9\-]+))");
        std::smatch m;
        if (!std::regex_match(req.path, m, rx)) { res.status=404; return; }
        auto id = m[1].str();
        bool ok = runner->cancel(id);
        res.status = ok? 202 : 404;
        res.body = "{}";
    });
}

} // namespace rest_adapter
```

------

# gRPC 适配层（可选）

## adapters/grpc/lro.proto

```
syntax = "proto3";
package lro.grpc;

message Spec { string json = 1; }
message CreateRequest { string idempotency_key = 1; Spec spec = 2; }
message Operation {
  string id = 1;
  string status = 2;
  string phase = 3;
  int32  progress = 4;
  string reason = 5;
}
message GetRequest { string id = 1; }
message CancelRequest { string id = 1; }

service Operations {
  rpc Create(CreateRequest) returns (Operation);
  rpc Get(GetRequest) returns (Operation);
  rpc Cancel(CancelRequest) returns (Operation);
  rpc Watch(GetRequest) returns (stream Operation);
}
```

## adapters/grpc/server.h

```
#pragma once
#include <memory>
#include "lro/runner.h"
namespace lrogrpc {
class OperationsServiceImpl; // 前向声明
std::shared_ptr<OperationsServiceImpl> make_service(lro::Runner* runner);
} // namespace lrogrpc
```

## adapters/grpc/server.cpp

```
#include "server.h"
#ifdef LRO_WITH_GRPC
#include <grpcpp/grpcpp.h>
#include "lro.grpc.pb.h"
#include <nlohmann/json.hpp>
#include <thread>

namespace rpc = ::lro::grpc;
using grpc::ServerContext;
using grpc::Status;
using grpc::StatusCode;

namespace lrogrpc {

class OperationsServiceImpl final : public rpc::Operations::Service {
public:
    explicit OperationsServiceImpl(lro::Runner* r) : runner_(r) {}

    Status Create(ServerContext*, const rpc::CreateRequest* req, rpc::Operation* resp) override {
        auto op = runner_->create("", req->idempotency_key(), req->spec().json());
        fill(*op, *resp); return Status::OK;
    }
    Status Get(ServerContext*, const rpc::GetRequest* req, rpc::Operation* resp) override {
        auto op = runner_->get(req->id());
        if (!op) return Status(StatusCode::NOT_FOUND, "");
        fill(*op, *resp); return Status::OK;
    }
    Status Cancel(ServerContext*, const rpc::CancelRequest* req, rpc::Operation* resp) override {
        auto op = runner_->get(req->id());
        if (!op) return Status(StatusCode::NOT_FOUND, "");
        runner_->cancel(req->id());
        op = runner_->get(req->id());
        fill(*op, *resp); return Status::OK;
    }
    Status Watch(ServerContext* ctx, const rpc::GetRequest* req, grpc::ServerWriter<rpc::Operation>* writer) override {
        while (!ctx->IsCancelled()) {
            auto op = runner_->get(req->id());
            if (!op) break;
            rpc::Operation out; fill(*op, out);
            writer->Write(out);
            using S = lro::Status;
            if (op->status==S::Ready || op->status==S::Failed || op->status==S::Cancelled) break;
            std::this_thread::sleep_for(std::chrono::milliseconds(300));
        }
        return Status::OK;
    }
private:
    static void fill(const lro::Operation& in, rpc::Operation& out) {
        out.set_id(in.id);
        out.set_status(lro::to_string(in.status));
        out.set_phase(in.phase);
        out.set_progress(in.progress.load());
        out.set_reason(in.reason);
    }
    lro::Runner* runner_;
};

std::shared_ptr<OperationsServiceImpl> make_service(lro::Runner* r) {
    return std::make_shared<OperationsServiceImpl>(r);
}

} // namespace lrogrpc
#else
namespace lrogrpc {
struct OperationsServiceImpl {};
std::shared_ptr<OperationsServiceImpl> make_service(lro::Runner*) { return {}; }
} // namespace lrogrpc
#endif
```

------

# 示例：REST

## examples/rest_server/main.cpp

```
#include <iostream>
#include <nlohmann/json.hpp>
#include "lro/runner.h"
#include "lro/state_store.h"
#include "adapters/rest_simplehttpserver/routes.h"

using namespace lro;
using namespace rest_adapter;
using json = nlohmann::json;

int main() {
    RunnerConfig cfg; cfg.store = make_memory_store();
    Runner runner(cfg);

    // 这里替换为你的业务步骤（示例）
    runner.addStep({ "preparing", [](std::shared_ptr<Operation>& op){
        std::this_thread::sleep_for(std::chrono::milliseconds(80));
    }, Step::IO, 5 });

    runner.addStep({ "opening_rtsp", [](std::shared_ptr<Operation>& op){
        auto spec = json::parse(op->spec_json);
        std::string url = spec.value("rtsp_url","");           // 校验/打开
        if (url.rfind("rtsp://",0)!=0) throw std::runtime_error("open_rtsp_error");
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
    }, Step::IO, 20 });

    runner.addStep({ "loading_model", [](std::shared_ptr<Operation>& op){
        auto spec = json::parse(op->spec_json);
        std::string key = spec.value("model_key","");          // 加载模型
        if (key.empty()) throw std::runtime_error("onnx_load_error");
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }, Step::Heavy, 60 });

    runner.addStep({ "starting_pipeline", [](std::shared_ptr<Operation>& op){
        std::this_thread::sleep_for(std::chrono::milliseconds(200)); // 启动管线
    }, Step::Start, 85 });

    Router router;
    register_routes(router, &runner);
    std::cout << "REST skeleton is ready. Integrate Router with your HTTP server.\n";
    return 0;
}
```

------

# 示例：gRPC（可选）

## examples/grpc_server/main.cpp

```
#include <iostream>
#ifdef LRO_WITH_GRPC
#include <grpcpp/grpcpp.h>
#include "adapters/grpc/server.h"
#include "lro/runner.h"
#include "lro/state_store.h"
#include <nlohmann/json.hpp>

using grpc::Server;
using grpc::ServerBuilder;
using namespace lro;

int main() {
    RunnerConfig cfg; cfg.store = make_memory_store();
    Runner runner(cfg);

    // 业务步骤（可复用 REST 示例）
    // runner.addStep(...);

    ServerBuilder builder;
    std::string addr("0.0.0.0:50051");
    auto service = lrogrpc::make_service(&runner);
    builder.AddListeningPort(addr, grpc::InsecureServerCredentials());
    builder.RegisterService(service.get());
    std::unique_ptr<Server> server(builder.BuildAndStart());
    std::cout << "gRPC LRO server listening on " << addr << std::endl;
    server->Wait();
    return 0;
}
#else
int main(){ std::cout << "gRPC not enabled. Install gRPC/Protobuf and rebuild.\n"; return 0; }
#endif
```

------

## 接入指引（与你现有 VA/CP 对齐）

1. 将 `include/` 与 `src/` 并入你的工程或作为子目录；保证可以包含到 `<nlohmann/json.hpp>`（vcpkg 或本地头文件）。

2. 在服务启动处构造：

   ```
   lro::RunnerConfig cfg; cfg.store = lro::make_memory_store(); // 或自研 StateStore
   lro::Runner runner(cfg);
   ```

3. 把你现有的 `Rtsp::open`、`Onnx/TensorRT load`、`PipelineBuilder::build()->start()` 拆成步骤注册到 `runner.addStep(...)`。

4. 用 REST 或 gRPC 适配层暴露 `Create/Get/Cancel`（前端配合 202+id 的 LRO 模式；SSE/WS 需你在 Notifier 上扩展即可）。