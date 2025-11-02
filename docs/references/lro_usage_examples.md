# LRO 使用示例（Runner/Admission/Watch）

## 构建与示例运行
- 构建示例：`ninja -C video-analyzer/build-ninja example_rest example_grpc`
- 运行 REST 示例（伪 Router）：`video-analyzer/build-ninja/lro/example_rest.exe`
- 运行 gRPC 示例（若启用）：`video-analyzer/build-ninja/lro/example_grpc.exe`

## 连续 watch：最小用法
```
#include "lro/runner.h"
#include "lro/state_store.h"

lro::RunnerConfig cfg; cfg.store = lro::make_memory_store();
lro::Runner runner(cfg);

auto handle = runner.watch("op-123",
  [](const std::shared_ptr<lro::Operation>& op){
    if (!op) {/* not_found */ return;}
    // on phase change or keepalive
    // emit SSE / log
  },
  lro::Runner::WatchOptions{200, 10000});
// …需要时停止：handle->stop.store(true);
```

## Retry-After 估算（解耦策略）
```
#include "lro/admission.h"
#include "lro/retry_estimator.h"

auto adm = std::make_shared<lro::AdmissionPolicy>();
adm->setBucketCapacity("open", 2);
adm->setRetryEstimator(std::make_shared<lro::SimpleRetryEstimator>());
int retry_after = adm->estimateRetryAfterSeconds(/*queue=*/7, /*slots=*/2); // -> 4
```

## Metrics（可选）
- 库不绑定领域指标；如需暴露，建议从 Runner.get()/store 快照构建：
  - 队列长度：非终态计数
  - 在途：非终态计数
  - 状态分布：op->phase 计数聚合
  - 完成总数：按终态分类计数
  - 时长直方图：created_at→finished_at 分桶

