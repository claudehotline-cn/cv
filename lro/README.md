# LRO (Long-Running Operation) Library

A small, header-first C++ library for modeling and running long-running operations (LRO):
status machine, execution pipeline, per-bucket admission control, fair scheduling,
merge/idempotency, backpressure (Retry-After estimation), notifier hooks, and metrics snapshots.

## 使用方式

1) 作为子目录引入（推荐）

```
add_subdirectory(lro)
# 编译库目标（建议）：
target_link_libraries(your_target PRIVATE lro::lro_runtime)
# 仅头文件目标（可选）：
# target_link_libraries(your_target PRIVATE lro::lro)
```

2) 安装后使用 find_package（支持版本约束）

```
find_package(lro CONFIG REQUIRED)             # 或 find_package(lro 1.0 CONFIG REQUIRED)
target_link_libraries(your_target PRIVATE lro::lro_runtime)
```

### 构建与运行示例

在顶层工程（含本仓 lro 子目录且已生成 build）中：

```
# 仅构建示例（REST + gRPC，gRPC 需要 vcpkg 安装 Protobuf/gRPC）
ninja -C video-analyzer/build-ninja example_rest example_grpc

# 运行 REST 示例（伪 Router，无真实 HTTP）：
video-analyzer/build-ninja/lro/example_rest.exe

# 运行 gRPC 示例（若启用）：
video-analyzer/build-ninja/lro/example_grpc.exe
```

### 连续 watch 与 Retry-After 估算（示例）

```
#include "lro/runner.h"
#include "lro/state_store.h"
#include "lro/admission.h"
#include "lro/retry_estimator.h"

// 1) Runner + MemoryStore
lro::RunnerConfig cfg; cfg.store = lro::make_memory_store();
lro::Runner runner(cfg);

// 2) 连续 watch：phase 变更或 keepalive 时回调
auto h = runner.watch("op-1",
    [](const std::shared_ptr<lro::Operation>& op){ if (!op) return; /* emit SSE/event */ },
    lro::Runner::WatchOptions{200, 10000});
// 停止：h->stop.store(true);

// 3) Admission + 自定义 RetryEstimator（解耦估算策略）
auto adm = std::make_shared<lro::AdmissionPolicy>();
adm->setBucketCapacity("open", 2);
adm->setRetryEstimator(std::make_shared<lro::SimpleRetryEstimator>());
int ra = adm->estimateRetryAfterSeconds(/*queue=*/5, /*slots=*/2); // => ceil(5/2)=3
```

## Minimum C++ API（核心）

- include/lro/runner.h – Runner/Operation/Step/RunnerConfig
- include/lro/state_store.h – IStateStore/MemoryStore/WalStoreAdapter (interfaces)
- include/lro/admission.h – AdmissionPolicy (multi-bucket + fair window)
- include/lro/metrics.h – 通用指标样例类型（库不依赖，可选使用）
- include/lro/notifier.h – INotifier（SSE/WS/Webhook）
- include/lro/reason.h – normalizeReason 钩子（占位，非业务化）
  
可选扩展：
- include/lro/retry_estimator.h – IRetryEstimator（重试估算 SPI，Admission 可注入）

Adapters（示例）
- include/lro/adapters/rest_simple.h – 简易 REST 接线辅助（示例）
- 示例程序：
  - example_rest（无需真实 HTTP 框架的伪路由演示）
  - example_grpc（条件启用，使用 Protobuf/gRPC）

本仓库提供编译库 lro_runtime；也保留头文件目标 lro::lro 以便快速接入。根据规模选择其一。

