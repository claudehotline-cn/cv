我看过你上传的 `cv-IOBinding.zip`，这里先给出 **`video-analyzer/` 的真实代码结构梳理**（已排除 `build-ninja` 产物），并结合你“短期将控制平面留在 video-analyzer 内、后期可平滑拆分”的目标，给出**精准映射与最小改造建议**。

（我已把目录树渲染出来，便于你核对：见上方“video-analyzer 项目结构”输出。）

------

## 我看到的核心模块与职责

- **配置层（YAML 驱动）**
  - `config/`：`app.yaml / models.yaml / profiles.yaml` 与 `graphs/*.yaml`（多阶段图的 YAML 编排）。
  - `src/ConfigLoader.*`：配置加载。
- **核心运行时（Core）**
  - `src/core/`：
    - `engine_manager.* / pipeline.* / pipeline_builder.*`：流水线/引擎管理与构建。
    - `buffer_pool.* / gpu_buffer_pool.*`：CPU/GPU 缓冲池。
    - `global_metrics.* / drop_metrics.* / metrics_text_builder.hpp`：度量聚合（Prometheus 文本拼装基础已具备）。
    - `logger.*`：日志封装。
    - 结论：**已经有“引擎+构建器+度量+内存池”的坚实底座**。
- **分析器执行栈（Analyzer & Multistage）**
  - `src/analyzer/`：
    - `analyzer.*`：入口/编排层。
    - `ort_session.*`：ONNX Runtime **封装**（可承接 TensorRT EP 与 IOBinding）。
    - `cuda/*.cu`：CUDA 核（`preproc_letterbox / yolo_decode / yolo_nms / overlay / overlay_nv12` 等）。
  - `src/analyzer/multistage/`
    - `graph.* / runner.* / registry.* / interfaces.hpp`：**多阶段图**的图结构、执行器与节点注册中心。
    - `builder_yaml.*`：从 YAML 生成图（与 `core/pipeline_builder.*` 功能有交叠）。
    - `node_*`：预处理/模型/NMS/Overlay/KPT/ROI 批处理/ReID 平滑等**节点实现**（含 `node_roi_batch_cuda.*`）。
  - 结论：**“composition_root 思想已落地”**，并且 **多阶段节点库完整**。
- **媒体与传输**
  - `src/media/`：
    - 源：`source_ffmpeg_rtsp.* / source_nvdec_cuda.* / source_switchable_rtsp.*`
    - 编码：`encoder_h264_ffmpeg.* / encoder_h264_nvenc.*`
    - 传输：`transport_whip.* / transport_webrtc_datachannel.* / transport.hpp`
  - 结论：**RTSP 拉流（FFmpeg/NVDEC）、H.264 编码（FFmpeg/NVENC）、WHIP/WebRTC datachannel** 都已就位。
- **服务与工具**
  - `src/server/rest.*`：已有一个 **REST 入口**（可作为“内嵌控制平面”的雏形）。
  - `tools/nvcc_wrap.py`：NVCC 包装脚本（解决 MSVC 标志透传问题，很实用）。
  - `test/`：`unit/`（如 `test_overlay_cuda.cpp` / `test_postproc_threshold.cpp`）与 `scripts/`（若干验证脚本）。

> 总体评价：**结构清晰，功能层次完备**。已经具备把控制平面“内嵌运行”的基础，也方便后续抽离。

------

## 与我建议的目标架构的一一映射

| 目标组件                             | 你现状                                                       | 建议映射/命名                                                |
| ------------------------------------ | ------------------------------------------------------------ | ------------------------------------------------------------ |
| composition_root（图构建与执行）     | `src/core/*` + `src/analyzer/multistage/*` + `src/composition_root.*` | 建议把**图构建器**统一在 `composition_root/graph_builder.*`，节点注册继续用 `multistage/registry.*` |
| 节点库（预处理/模型/NMS/Overlay…）   | `src/analyzer/multistage/node_*` + `src/analyzer/cuda/*`     | 维持现状，适当把 CUDA 内核与对应 node 贴得更近（按功能子目录分组） |
| 媒体 I/O（Source/Encoder/Transport） | `src/media/*`                                                | 暂时维持；为未来 VSM 预留 `src/io/from_vsm_link.*` 抽象      |
| 内嵌控制平面（API/控制器/存储）      | `src/server/rest.*` + `src/ConfigLoader.*`                   | **新建 `src/control_plane_embedded/`**：`api/ (迁移 rest)`、`controllers/`、`store/inmem/`、`scheduler/local/`、`ports/` |
| 指标导出                             | `src/core/global_metrics.*` 等                               | **新建 `src/exporters/prometheus_exporter.\*`**，统一 `/metrics` 暴露（文本格式你已有构件） |
| 协议/Schema                          | YAML（`config/graphs/`）                                     | 保留 YAML，同时**新增 `proto/`（`analyzer_control.proto`、`pipeline.proto`）**，后期拆分无需改接口 |

------

## 最少改动的重构清单（一步步做，不引入 DB/Nacos）

1. **落地内嵌控制平面目录**
    新建：

   ```
   src/control_plane_embedded/
     ├─ api/                # 把 src/server/rest.* 移到这里
     ├─ controllers/        # PipelineController：Reconcile Desired ↔ Runtime
     ├─ store/inmem/        # 仅内存态（后续可换 MySQL/Nacos）
     ├─ scheduler/local/    # 本机简易调度器
     └─ ports/              # iconfig_store / ievent_bus / imetrics_sink（预留可插拔口）
   ```

   `api/rest` → 调 `controllers`；控制器内部调用 **本地执行器** 与 `multistage/registry`。

2. **统一流水线构建器**
    现在有 `src/core/pipeline_builder.*` 与 `src/analyzer/multistage/builder_yaml.*` 两套路径，建议：

   - 提取为 `src/composition_root/graph_builder.*`（对上承接 YAML/Proto，两端统一出图）。
   - 复用 `multistage/registry.*` 作为唯一 `NodeRegistry`。

3. **加入 gRPC Schema（先本进程内回环调用）**
    新建 `proto/`：

   - `analyzer_control.proto`：`ApplyPipeline/Remove/HotSwap/Drain/GetStatus`
   - `pipeline.proto`：`Pipeline/NodeSpec`（未来外部控制平面直连，无需改视频侧）

   > 短期：REST→Controller→（本进程）gRPC Stub→Executor；长期：换成跨进程调用即可。

4. **抽象 VSM 链路（保持向后兼容）**
    新建 `src/io/from_vsm_link.*`：接口与适配层。

   - 当前先把 `src/media/source_*` 以一个默认实现挂进去；
   - 未来接入 video-source-manager 时，将本地实现替换为 **共享内存/IPC/gRPC 流** 即可。

5. **完整的 Prometheus 导出**
    新建 `src/exporters/prometheus_exporter.*`，把 `global_metrics/drop_metrics` 聚合为 `/metrics`，并将图/节点关键指标（FPS、延迟 P50/P95、GPU 显存、零拷贝命中率等）结构化。

6. **仓库卫生**

   - 把 `video-analyzer/build-ninja/**` 清理（`.gitignore` 已有，但建议删已提交产物）。
   - `tools/nvcc_wrap.py` 保留，确保 MSVC/Ninja 组合构建顺滑。

------

## 你可以立即落地的“目录补丁”（新增部分）

```
video-analyzer/
├─ proto/
│  ├─ analyzer_control.proto
│  └─ pipeline.proto
├─ src/
│  ├─ control_plane_embedded/
│  │  ├─ api/rest.{hpp,cpp}              # 从 src/server/ 迁入
│  │  ├─ controllers/pipeline_controller.{hpp,cpp}
│  │  ├─ store/inmem/inmem_store.{hpp,cpp}
│  │  ├─ scheduler/local/local_scheduler.{hpp,cpp}
│  │  └─ ports/{iconfig_store.hpp,ievent_bus.hpp,imetrics_sink.hpp}
│  ├─ composition_root/graph_builder.{hpp,cpp}  # 统一 builder
│  ├─ exporters/prometheus_exporter.{hpp,cpp}
│  └─ io/from_vsm_link.{hpp,cpp}                 # 预留与 VSM 对接
```

> 以上新增目录**不改变你现有执行路径**：先把 REST 调用接到 `controllers`，`controllers` 再走你现有的 `engine_manager + multistage/runner`。等 VSM 就绪，再把 `from_vsm_link` 替换为跨进程实现即可。

------

## 小结（对齐你的目标）

- 你的 `video-analyzer` 已具备 **多阶段图、ORT+CUDA 核、媒体输入/输出、REST 入口、度量基础**，完全适合**先内嵌控制平面**跑起来。
- 按上面“最少改动”的补丁落地后，**外部化控制平面**只需把 `control_plane_embedded/` 目录迁出为新仓库，REST/gRPC 地址指向外部服务即可；数据面（图、节点、执行器、媒体 I/O）无需大改。

# 关键文件示例

没问题！下面给出**关键文件示例**（最小可跑骨架/可直接粘贴到你仓库的新增文件），围绕你当前 `video-analyzer` 结构做“内嵌控制平面 + gRPC 下发 + /metrics 导出”，并补一份 `video-source-manager` 的控制面 gRPC 协议与服务骨架，后续可无缝外拆为独立控制平面。

> 说明参考：
>
> - gRPC/C++ 服务写法与 proto 组织（官方教程与风格指引）。[protobuf.dev+3gRPC+3gRPC+3](https://grpc.io/docs/languages/cpp/basics/?utm_source=chatgpt.com)
> - Prometheus `/metrics` 文本暴露规范（OpenMetrics 文本格式，默认路径 `/metrics`）。[prometheus.io+2prometheus.github.io+2](https://prometheus.io/docs/specs/om/open_metrics_spec/?utm_source=chatgpt.com)
> - ONNX Runtime IOBinding 的意图与收益（预分配 GPU I/O，减少 H2D/D2H 往返，后续你可在 `model_ort_trt` 中接入）。[onnxruntime.ai+2onnxruntime.ai+2](https://onnxruntime.ai/docs/performance/tune-performance/iobinding.html?utm_source=chatgpt.com)

------

# 1) `video-analyzer/proto/analyzer_control.proto`

最小控制面服务，支持 Apply/Remove/HotSwap/Drain/GetStatus；后续外拆时**无需改数据面**。

```
syntax = "proto3";
package va.v1;

option cc_enable_arenas = true;

// 控制平面 → video-analyzer
service AnalyzerControl {
  rpc ApplyPipeline(ApplyPipelineRequest) returns (ApplyPipelineReply);
  rpc RemovePipeline(RemovePipelineRequest) returns (RemovePipelineReply);
  rpc HotSwapModel(HotSwapModelRequest) returns (HotSwapModelReply);
  rpc Drain(DrainRequest) returns (DrainReply);
  rpc GetStatus(GetStatusRequest) returns (GetStatusReply);
}

// 直接承载 pipeline.proto 的序列化结果（二选一：JSON bytes 或 protobuf bytes）
message PipelineSpec { bytes serialized = 1; string format = 2; } // "proto" | "json"

message ApplyPipelineRequest { string pipeline_name = 1; PipelineSpec spec = 2; string revision = 3; }
message ApplyPipelineReply   { bool accepted = 1; string msg = 2; }

message RemovePipelineRequest { string pipeline_name = 1; }
message RemovePipelineReply   { bool removed = 1; string msg = 2; }

message HotSwapModelRequest { string pipeline_name = 1; string node = 2; string model_uri = 3; }
message HotSwapModelReply   { bool ok = 1; string msg = 2; }

message DrainRequest { string pipeline_name = 1; int32 timeout_sec = 2; }
message DrainReply   { bool drained = 1; }

message GetStatusRequest { string pipeline_name = 1; }
message GetStatusReply   { string phase = 1; string metrics_json = 2; }
```

------

# 2) `video-analyzer/proto/pipeline.proto`

最小 Pipeline/Node 结构，与你现有 `graphs/*.yaml` 一致化（先顺序执行，后面再扩展 DAG）。

```
syntax = "proto3";
package va.v1;

message NodeParamKV { string key = 1; string value = 2; }

message NodeSpec {
  string name = 1;                 // det/nms/overlay/sink...
  string type = 2;                 // onnx_model/nms/cuda_overlay/webrtc_out...
  repeated NodeParamKV params = 3; // {k,v} 列表，避免频繁改 schema
}

message Pipeline {
  string name = 1;
  string source_ref = 2;           // e.g. "source/rtsp-entrance-01"
  repeated NodeSpec nodes = 3;     // 顺序即执行序（后期可引入 edges[] 表达有向图）
}
```

------

# 3) `video-analyzer/src/control_plane_embedded/controllers/pipeline_controller.hpp`

把“期望态（YAML/Proto）”编译成可执行图并运行；与现有 `core/engine_manager.* + analyzer/multistage/*` 对接。

```
#pragma once
#include <string>
#include <unordered_map>
#include <memory>
#include <mutex>
#include <atomic>

#include "pipeline.pb.h"           // va.v1::Pipeline
#include "util/status.h"           // 你仓库已有：统一错误码/Status
#include "composition_root.hpp"    // 现有：对外暴露 Graph/Executor 或你定义的适配接口

namespace va {

class IGraphAdapter {
public:
  virtual ~IGraphAdapter() = default;
  // 将 protobuf Pipeline 构建为可执行 Graph，并准备 Executor
  virtual std::unique_ptr<Graph> BuildGraph(const va::v1::Pipeline& spec, std::string* err) = 0;
  virtual std::unique_ptr<Executor> CreateExecutor(Graph* graph, std::string* err) = 0;
};

class PipelineController {
public:
  explicit PipelineController(IGraphAdapter* adapter);
  Status Apply(const std::string& name, const va::v1::Pipeline& spec, const std::string& rev);
  Status Remove(const std::string& name);
  Status HotSwapModel(const std::string& name, const std::string& node, const std::string& uri);
  Status Drain(const std::string& name, int timeout_sec);
  std::string GetStatus(const std::string& name);

private:
  struct Runtime {
    std::unique_ptr<Graph>     graph;
    std::unique_ptr<Executor>  executor;
    std::string                revision;
    std::atomic<bool>          ready{false};
  };
  std::mutex mu_;
  std::unordered_map<std::string, Runtime> pipelines_;
  IGraphAdapter* adapter_;
};

} // namespace va
```

------

# 4) `video-analyzer/src/control_plane_embedded/controllers/pipeline_controller.cpp`

与现有执行器打通（这里只给出**核心路径**，具体细节你可接入 `engine_manager` / `runner`）。

```
#include "pipeline_controller.hpp"
#include "util/logging.h"
#include "core/global_metrics.h"  // 已有：可在 Apply/Remove 处打点

using va::v1::Pipeline;

namespace va {

PipelineController::PipelineController(IGraphAdapter* adapter) : adapter_(adapter) {}

Status PipelineController::Apply(const std::string& name, const Pipeline& spec, const std::string& rev) {
  std::lock_guard<std::mutex> lk(mu_);
  std::string err;
  auto g = adapter_->BuildGraph(spec, &err);
  if (!g) return Status::InvalidArgument("BuildGraph failed: " + err);

  auto ex = adapter_->CreateExecutor(g.get(), &err);
  if (!ex) return Status::Internal("CreateExecutor failed: " + err);

  // 先停止旧流水线（滚动更新可按需分步：Drain→Warmup→Switch）
  auto it = pipelines_.find(name);
  if (it != pipelines_.end()) {
    it->second.executor->Stop();
    pipelines_.erase(it);
  }

  Runtime rt;
  rt.graph    = std::move(g);
  rt.executor = std::move(ex);
  rt.revision = rev;

  if (!rt.executor->Start(&err)) {
    return Status::Internal("Executor start failed: " + err);
  }
  rt.ready.store(true, std::memory_order_release);
  pipelines_.emplace(name, std::move(rt));
  LOG_INFO() << "[Pipeline] Applied name=" << name << " rev=" << rev;
  return Status::OK();
}

Status PipelineController::Remove(const std::string& name) {
  std::lock_guard<std::mutex> lk(mu_);
  auto it = pipelines_.find(name);
  if (it == pipelines_.end()) return Status::NotFound("pipeline not found");
  it->second.executor->Stop();
  pipelines_.erase(it);
  LOG_INFO() << "[Pipeline] Removed name=" << name;
  return Status::OK();
}

Status PipelineController::HotSwapModel(const std::string& name, const std::string& node, const std::string& uri) {
  std::lock_guard<std::mutex> lk(mu_);
  auto it = pipelines_.find(name);
  if (it == pipelines_.end()) return Status::NotFound("pipeline not found");
  return it->second.executor->HotSwapModel(node, uri);
}

Status PipelineController::Drain(const std::string& name, int timeout_sec) {
  std::lock_guard<std::mutex> lk(mu_);
  auto it = pipelines_.find(name);
  if (it == pipelines_.end()) return Status::NotFound("pipeline not found");
  return it->second.executor->Drain(timeout_sec);
}

std::string PipelineController::GetStatus(const std::string& name) {
  std::lock_guard<std::mutex> lk(mu_);
  auto it = pipelines_.find(name);
  if (it == pipelines_.end()) return R"({"phase":"NotFound"})";
  return it->second.executor->CollectStatusJson();
}

} // namespace va
```

------

# 5) `video-analyzer/src/control_plane_embedded/api/grpc_server.{hpp,cpp}`

实现 `AnalyzerControl`，把 RPC 映射到 `PipelineController`。

> 服务器结构遵循 gRPC/C++ 基础示例（同步或异步任选）。[gRPC+1](https://grpc.io/docs/languages/cpp/basics/?utm_source=chatgpt.com)

```
// grpc_server.hpp
#pragma once
#include <grpcpp/grpcpp.h>
#include "analyzer_control.grpc.pb.h"
#include "controllers/pipeline_controller.hpp"

namespace va {

class AnalyzerControlService final : public va::v1::AnalyzerControl::Service {
public:
  explicit AnalyzerControlService(PipelineController* ctl) : ctl_(ctl) {}
  ::grpc::Status ApplyPipeline(::grpc::ServerContext*, const va::v1::ApplyPipelineRequest* req,
                               va::v1::ApplyPipelineReply* resp) override;
  ::grpc::Status RemovePipeline(::grpc::ServerContext*, const va::v1::RemovePipelineRequest* req,
                                va::v1::RemovePipelineReply* resp) override;
  ::grpc::Status HotSwapModel(::grpc::ServerContext*, const va::v1::HotSwapModelRequest* req,
                              va::v1::HotSwapModelReply* resp) override;
  ::grpc::Status Drain(::grpc::ServerContext*, const va::v1::DrainRequest* req,
                       va::v1::DrainReply* resp) override;
  ::grpc::Status GetStatus(::grpc::ServerContext*, const va::v1::GetStatusRequest* req,
                           va::v1::GetStatusReply* resp) override;
private:
  PipelineController* ctl_;
};

std::unique_ptr<grpc::Server> StartGrpcServer(const std::string& addr, AnalyzerControlService* svc);

} // namespace va
// grpc_server.cpp
#include "api/grpc_server.hpp"
#include "pipeline.pb.h"
#include "util/json.h"

namespace va {

::grpc::Status AnalyzerControlService::ApplyPipeline(::grpc::ServerContext*, const va::v1::ApplyPipelineRequest* req,
                                                     va::v1::ApplyPipelineReply* resp) {
  va::v1::Pipeline p;
  if (req->spec().format() == "proto") {
    p.ParseFromString(req->spec().serialized());
  } else { // json
    if (!FromJson(req->spec().serialized(), &p)) {
      resp->set_accepted(false); resp->set_msg("invalid pipeline json"); return ::grpc::Status::OK;
    }
  }
  auto st = ctl_->Apply(req->pipeline_name(), p, req->revision());
  resp->set_accepted(st.ok());
  resp->set_msg(st.message());
  return ::grpc::Status::OK;
}

::grpc::Status AnalyzerControlService::RemovePipeline(::grpc::ServerContext*, const va::v1::RemovePipelineRequest* req,
                                                      va::v1::RemovePipelineReply* resp) {
  auto st = ctl_->Remove(req->pipeline_name());
  resp->set_removed(st.ok()); resp->set_msg(st.message());
  return ::grpc::Status::OK;
}

::grpc::Status AnalyzerControlService::HotSwapModel(::grpc::ServerContext*, const va::v1::HotSwapModelRequest* req,
                                                    va::v1::HotSwapModelReply* resp) {
  auto st = ctl_->HotSwapModel(req->pipeline_name(), req->node(), req->model_uri());
  resp->set_ok(st.ok()); resp->set_msg(st.message());
  return ::grpc::Status::OK;
}

::grpc::Status AnalyzerControlService::Drain(::grpc::ServerContext*, const va::v1::DrainRequest* req,
                                             va::v1::DrainReply* resp) {
  auto st = ctl_->Drain(req->pipeline_name(), req->timeout_sec());
  resp->set_drained(st.ok());
  return ::grpc::Status::OK;
}

::grpc::Status AnalyzerControlService::GetStatus(::grpc::ServerContext*, const va::v1::GetStatusRequest* req,
                                                 va::v1::GetStatusReply* resp) {
  resp->set_phase("Unknown");
  resp->set_metrics_json(ctl_->GetStatus(req->pipeline_name()));
  return ::grpc::Status::OK;
}

std::unique_ptr<grpc::Server> StartGrpcServer(const std::string& addr, AnalyzerControlService* svc) {
  grpc::ServerBuilder b;
  b.AddListeningPort(addr, grpc::InsecureServerCredentials());
  b.RegisterService(svc);
  return b.BuildAndStart();
}

} // namespace va
```

------

# 6) `video-analyzer/src/exporters/prometheus_exporter.{hpp,cpp}`

将你现有 `core/global_metrics.*` 汇总并按 **OpenMetrics/Prometheus 文本格式**暴露在 `/metrics`。[prometheus.io+1](https://prometheus.io/docs/specs/om/open_metrics_spec/?utm_source=chatgpt.com)

```
// prometheus_exporter.hpp
#pragma once
#include <string>
#include <thread>
#include <atomic>
#include <functional>

// 轻量 HTTP：你可用现有 REST 服务或任意微型 HTTP 库。
// 这里只定义接口，便于接到 src/server/rest.*
class PrometheusExporter {
public:
  using CollectorFn = std::function<std::string()>;

  PrometheusExporter() = default;
  ~PrometheusExporter() { Stop(); }

  // 绑定收集器：返回完整文本（含 # HELP/# TYPE），Metric 名称需遵循规范
  void SetCollector(CollectorFn fn) { collector_ = std::move(fn); }

  bool Start(const std::string& host, int port); // 监听 /metrics
  void Stop();

private:
  CollectorFn collector_;
  std::thread th_;
  std::atomic<bool> running_{false};
};
// prometheus_exporter.cpp
#include "exporters/prometheus_exporter.hpp"
#include "core/global_metrics.h" // 你现有的聚合指标

// 伪代码：用你已有 REST 服务把 /metrics 路由到 collector_()
// 确保输出遵循文本暴露规范：示例：
// # HELP va_pipeline_fps Frames per second of pipeline
// # TYPE va_pipeline_fps gauge
// va_pipeline_fps{pipeline="lineA"} 24.8
// # HELP va_infer_latency_ms Inference latency
// # TYPE va_infer_latency_ms summary
// va_infer_latency_ms_sum 12345
// va_infer_latency_ms_count 678
bool PrometheusExporter::Start(const std::string& host, int port) {
  running_.store(true);
  th_ = std::thread([this, host, port]() {
    // TODO: 接入你的 HTTP 服务器；收到 GET /metrics 时：
    // std::string body = collector_ ? collector_() : "";
    // write(body);
  });
  return true;
}

void PrometheusExporter::Stop() {
  if (!running_.load()) return;
  running_.store(false);
  if (th_.joinable()) th_.join();
}
```

> 规范要点：默认路径 `/metrics`；类型/帮助行建议带上；指标名用小写+下划线，标签键值用双引号。[prometheus.io+1](https://prometheus.io/docs/specs/om/open_metrics_spec/?utm_source=chatgpt.com)

------

# 7) `video-analyzer/src/io/from_vsm_link.{hpp,cpp}`

抽象“来自 VSM 的帧输入”。当前先**回退到本地 RTSP/NVDEC**（你已有实现），后续替换为共享内存或 gRPC 流。

```
// from_vsm_link.hpp
#pragma once
#include <memory>
#include <string>

struct Frame { /* TODO: 你的帧结构：pts/格式/设备内存指针等 */ };

class FromVSMLink {
public:
  virtual ~FromVSMLink() = default;
  virtual bool Start(const std::string& source_ref, std::string* err) = 0;
  virtual bool Read(Frame* out, int timeout_ms) = 0;
  virtual void Stop() = 0;
};

// 默认实现：直接用你现有的 src/media/source_* 组件
std::unique_ptr<FromVSMLink> CreateLocalSourceFallback();
// from_vsm_link.cpp
#include "io/from_vsm_link.hpp"
#include "media/source_switchable_rtsp.hpp" // 你仓库已有
#include "util/logging.h"

namespace {
class LocalSource : public FromVSMLink {
public:
  bool Start(const std::string& source_ref, std::string* err) override {
    // TODO: 解析 source_ref（rtsp://...），调用现有 FFmpeg/NVDEC 拉流
    return true;
  }
  bool Read(Frame* out, int /*timeout_ms*/) override {
    // TODO: 从本地解码队列取帧 → 填充 Frame（支持 GPU 零拷贝时填设备指针）
    return true;
  }
  void Stop() override { /* TODO */ }
};
} // namespace

std::unique_ptr<FromVSMLink> CreateLocalSourceFallback() {
  return std::make_unique<LocalSource>();
}
```

------

# 8) `video-source-manager/proto/source_control.proto`

控制平面/分析器 → VSM：Attach/Detach/GetHealth（与你之前约定一致）。

```
syntax = "proto3";
package vsm.v1;

service SourceControl {
  rpc Attach(AttachRequest) returns (AttachReply);
  rpc Detach(DetachRequest) returns (DetachReply);
  rpc GetHealth(GetHealthRequest) returns (GetHealthReply);
}

message AttachRequest {
  string attach_id   = 1;                  // 幂等键
  string source_uri  = 2;                  // rtsp://... 未来可扩展 whip://...
  string pipeline_id = 3;                  // 下游标识（路由/计费）
  map<string,string> options = 4;          // fps/decoder/超时等
}
message AttachReply { bool accepted = 1; string msg = 2; }

message DetachRequest { string attach_id = 1; }
message DetachReply  { bool removed = 1; string msg = 2; }

message GetHealthRequest {}
message GetHealthReply { repeated StreamStat streams = 1; }
message StreamStat {
  string attach_id = 1;
  double fps       = 2;
  double rtt_ms    = 3;
  double jitter_ms = 4;
  double loss_pct  = 5;
  string phase     = 6;   // Ready/Connecting/Backoff/Failed
}
```

------

# 9) `video-source-manager/src/app/rpc/grpc_server.{h,cc}`

最小 gRPC 服务实现（VSM 侧）。之后你可把帧输出接**共享内存/环形队列/gRPC 流**。

```
// grpc_server.h
#pragma once
#include <grpcpp/grpcpp.h>
#include "source_control.grpc.pb.h"

class SourceController; // 你在 VSM 侧的业务类（负责拉流与会话表）

class SourceControlService final : public vsm::v1::SourceControl::Service {
public:
  explicit SourceControlService(SourceController* ctl) : ctl_(ctl) {}
  ::grpc::Status Attach(::grpc::ServerContext*, const vsm::v1::AttachRequest*, vsm::v1::AttachReply*) override;
  ::grpc::Status Detach(::grpc::ServerContext*, const vsm::v1::DetachRequest*, vsm::v1::DetachReply*) override;
  ::grpc::Status GetHealth(::grpc::ServerContext*, const vsm::v1::GetHealthRequest*, vsm::v1::GetHealthReply*) override;
private:
  SourceController* ctl_;
};
// grpc_server.cc
#include "grpc_server.h"
#include "app/source_controller.h"  // 你的 VSM 侧控制器
#include "util/logging.h"

::grpc::Status SourceControlService::Attach(::grpc::ServerContext*, const vsm::v1::AttachRequest* req,
                                            vsm::v1::AttachReply* resp) {
  std::string err;
  bool ok = ctl_->Attach(req->attach_id(), req->source_uri(), req->pipeline_id(),
                         std::map<std::string,std::string>(req->options().begin(), req->options().end()), &err);
  resp->set_accepted(ok); resp->set_msg(err);
  return ::grpc::Status::OK;
}

::grpc::Status SourceControlService::Detach(::grpc::ServerContext*, const vsm::v1::DetachRequest* req,
                                            vsm::v1::DetachReply* resp) {
  std::string err;
  bool ok = ctl_->Detach(req->attach_id(), &err);
  resp->set_removed(ok); resp->set_msg(err);
  return ::grpc::Status::OK;
}

::grpc::Status SourceControlService::GetHealth(::grpc::ServerContext*, const vsm::v1::GetHealthRequest*,
                                               vsm::v1::GetHealthReply* resp) {
  for (const auto& s : ctl_->Collect()) {
    auto* out = resp->add_streams();
    out->set_attach_id(s.id);
    out->set_fps(s.fps);
    out->set_rtt_ms(s.rtt_ms);
    out->set_jitter_ms(s.jitter_ms);
    out->set_loss_pct(s.loss_pct);
    out->set_phase(s.phase);
  }
  return ::grpc::Status::OK;
}
```

------

## 如何与你现有代码对接的要点

- **图构建路径**：把你现有 `src/analyzer/multistage/builder_yaml.*` 的逻辑，抽象到 `IGraphAdapter::BuildGraph()` 实现里；这样 YAML/Proto 双栈都能复用同一套 `registry/runner`。
- **执行器**：你已有 `engine_manager/pipeline/executor`，在 `IGraphAdapter::CreateExecutor()` 内部完成绑定。
- **IOBinding/TRT**：在 `model_ort_trt.*` 中根据 `NodeSpec.params` 读取 `provider=tensorrt / iobinding=true`，并按 ORT IOBinding 方式预分配 GPU I/O（减少拷贝）。[onnxruntime.ai](https://onnxruntime.ai/docs/performance/tune-performance/iobinding.html?utm_source=chatgpt.com)
- **/metrics**：把你 `global_metrics` 汇总为上面的文本格式，暴露在 `/metrics`（建议保持 5s 抓取周期）。[prometheus.io](https://prometheus.io/docs/specs/om/open_metrics_spec/?utm_source=chatgpt.com)