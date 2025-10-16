可以，而且建议你直接把“两阶段”的抽象升级成**N 阶段 DAG（有向无环图）\**的“通用多阶段 Analyzer”。下面给你一份\**可直接落库**的方案：架构思路 + 目录结构 + 通用接口 + Graph 执行器 + 工厂注册机制 + 示例节点 + YAML 配置例子。保持你现有分层不变（媒体/管线/缓冲池/会话抽象都不改签名），只是**在 analyzer 层新增一个小框架**来编排多阶段。

------

# 目标与原则（与现架构对齐）

- **通用**：Stage 可自由组合、分支、汇合；支持“全图→ROI→再推理→渲染”等常见形态。
- **零拷贝**：节点之间传递的都是 `FrameSurface / TensorView / ROI` 的**句柄**（来自你已有 `Host/GpuBufferPool`）。
- **单流常驻**：同一路视频默认一条 `cudaStream`，事件/Graph 串起各节点；可选开启 CUDA Graph 捕获整条子图。
- **OCP / DIP / SRP / LSP**：新增算法=新增一个节点类；通过 **NodeFactory** 注入，不改现有代码。

------

# 目录结构（新增，不改你原有文件）

```
src/
  analyzer/
    multistage/
      interfaces.hpp          # 通用数据结构 & 基类接口
      graph.hpp               # 图结构（节点/边/拓扑）
      graph.cpp
      registry.hpp            # 节点工厂注册表
      registry.cpp
      nodes_common.hpp        # 通用辅助（端口名、工具函数）
      # 示例节点（可按需精简/扩展）
      node_preproc_letterbox.hpp
      node_preproc_letterbox.cpp
      node_model.hpp          # 通用模型节点(ORT/TRT) 单/多输出
      node_model.cpp
      node_nms.hpp
      node_nms.cpp
      node_roi_batch.hpp
      node_roi_batch.cpp
      node_kpt_decode.hpp
      node_kpt_decode.cpp
      node_overlay.hpp
      node_overlay.cpp
    # 你已有的 CUDA 内核可以重用；新增 ROI warp 如需：
  analyzer/cuda/
      roi_warp_affine_kernel.cu   # (可选) NV12→NCHW+norm 的批量ROI仿射
```

------

# 通用接口（最小可编骨架）

## `interfaces.hpp`

```
#pragma once
#include <string>
#include <vector>
#include <unordered_map>
#include <memory>
#include <variant>
#include "core/utils.hpp"
#include "core/buffer_pool.hpp"

namespace analyzer::ms {

// —— 轻量数据实体（句柄语义）——
struct Roi {
  int   id = -1;    // track或临时ID
  float x1=0, y1=0, x2=0, y2=0;
  float score=0;
  int   cls=-1;
};

using Attr = std::variant<int64_t, double, float, std::string>;
using TensorDict = std::unordered_map<std::string, core::TensorView>;
using AttrDict   = std::unordered_map<std::string, Attr>;
using RoiDict    = std::unordered_map<std::string, std::vector<Roi>>;

// —— Packet：节点之间传递的“帧级容器”——
struct Packet {
  // 必需：原始帧（NV12/GPU）
  core::FrameSurface frame;
  // 可选：张量/ROI/属性（由各节点按键名放入/读取）
  TensorDict tensors;
  RoiDict    rois;
  AttrDict   attrs;
};

// —— 节点上下文：同一路统一流/池/会话仓库等 —— 
struct NodeContext {
  cudaStream_t stream = nullptr;          // 同一路唯一流（由你的 GpuRuntime 提供）
  core::HostBufferPool* host_pool = nullptr;
  core::GpuBufferPool*  gpu_pool  = nullptr;
  // 可选：引擎/会话注册器、日志器等
  void* engine_registry = nullptr;        // 你已有 EngineRegistry 可传进来
  void* logger = nullptr;
};

// —— 节点基类 —— 
class INode {
public:
  virtual ~INode() = default;
  // 生命周期
  virtual bool open (NodeContext&) { return true; }
  virtual void close(NodeContext&) {}
  // 处理一次帧（可读写 inout；若需要branch/fan-out，可在 attrs/rois/tensors 中放多路键）
  virtual bool process(Packet& inout, NodeContext&) = 0;
  // 端口声明（便于静态检查/配置校验；返回需要的键名与产生的键名）
  virtual std::vector<std::string> inputs()  const { return {}; }
  virtual std::vector<std::string> outputs() const { return {}; }
};

// —— 智能指针别名 —— 
using NodePtr = std::shared_ptr<INode>;

} // namespace analyzer::ms
```

## `graph.hpp / graph.cpp`（拓扑 & 执行器）

```
// graph.hpp
#pragma once
#include "interfaces.hpp"
#include <unordered_map>

namespace analyzer::ms {

struct Edge { int from, to; };   // 简化：节点之间默认共享同一个 Packet

class Graph {
public:
  int add_node(NodePtr node, const std::string& name);
  void add_edge(int from, int to);
  bool compile();                // 拓扑排序 & 校验端口键（可选）
  bool run(Packet& p, NodeContext& ctx);  // 按拓扑依序调用各节点
  void clear();

private:
  std::vector<NodePtr> nodes_;
  std::vector<std::string> names_;
  std::vector<Edge> edges_;
  std::vector<int> topo_;
  std::unordered_map<std::string,int> name2id_;
};

} // namespace analyzer::ms
// graph.cpp
#include "graph.hpp"
#include <queue>

using namespace analyzer::ms;

int Graph::add_node(NodePtr node, const std::string& name){
  int id = (int)nodes_.size();
  nodes_.push_back(std::move(node));
  names_.push_back(name);
  name2id_[name]=id;
  return id;
}

void Graph::add_edge(int from, int to){ edges_.push_back({from,to}); }

bool Graph::compile(){
  // Kahn 拓扑
  int n = (int)nodes_.size();
  std::vector<int> indeg(n,0);
  for (auto& e: edges_) indeg[e.to]++;
  std::queue<int> q; for(int i=0;i<n;i++) if(indeg[i]==0) q.push(i);
  topo_.clear(); topo_.reserve(n);
  while(!q.empty()){ int u=q.front(); q.pop(); topo_.push_back(u);
    for (auto& e: edges_) if(e.from==u) if(--indeg[e.to]==0) q.push(e.to);
  }
  return (int)topo_.size()==n;
}

bool Graph::run(Packet& p, NodeContext& ctx){
  // 简化：单 Packet 贯穿（零拷贝）
  for (int id : topo_) {
    if (!nodes_[id]->process(p, ctx)) return false;
  }
  return true;
}

void Graph::clear(){ nodes_.clear(); edges_.clear(); topo_.clear(); names_.clear(); name2id_.clear(); }
```

## `registry.hpp / registry.cpp`（工厂/注册表）

```
// registry.hpp
#pragma once
#include "interfaces.hpp"
#include <functional>
#include <unordered_map>

namespace analyzer::ms {

using NodeCreateFn = std::function<NodePtr(const std::unordered_map<std::string,std::string>&)>;

class NodeRegistry {
public:
  static NodeRegistry& inst();
  void reg(const std::string& type, NodeCreateFn fn);
  NodePtr create(const std::string& type,
                 const std::unordered_map<std::string,std::string>& cfg) const;
private:
  std::unordered_map<std::string, NodeCreateFn> m_;
};

// 便捷宏
#define MS_REGISTER_NODE(TYPE, CLASS) \
  static bool __ms_reg_##CLASS = [](){ \
    analyzer::ms::NodeRegistry::inst().reg(TYPE, \
      [](const std::unordered_map<std::string,std::string>& cfg){ \
        return std::make_shared<CLASS>(cfg); }); \
    return true; }();

} // namespace analyzer::ms
// registry.cpp
#include "registry.hpp"
#include <stdexcept>

using namespace analyzer::ms;
NodeRegistry& NodeRegistry::inst(){ static NodeRegistry r; return r; }
void NodeRegistry::reg(const std::string& t, NodeCreateFn fn){ m_[t]=std::move(fn); }
NodePtr NodeRegistry::create(const std::string& t, const std::unordered_map<std::string,std::string>& cfg) const {
  auto it = m_.find(t); if (it==m_.end()) throw std::runtime_error("Unknown node type: "+t);
  return it->second(cfg);
}
```

------

# 示例节点（最小实现思路）

> 这些节点全部**在同一 cudaStream** 上工作；I/O 都使用你现有 `GpuBufferPool/HostBufferPool` 里的句柄。

## 1) 预处理（NV12→NCHW + letterbox + norm）

```
// node_preproc_letterbox.hpp
#pragma once
#include "interfaces.hpp"
namespace analyzer::ms {
class NodePreprocLetterbox : public INode {
public:
  explicit NodePreprocLetterbox(const std::unordered_map<std::string,std::string>& cfg);
  bool process(Packet& p, NodeContext& ctx) override;
  std::vector<std::string> outputs() const override { return {"tensor:det_input"}; }
private:
  int out_h_=640, out_w_=640, out_c_=3;
  core::TensorView det_input_;
};
} // ns
// node_preproc_letterbox.cpp
#include "node_preproc_letterbox.hpp"
using namespace analyzer::ms;

NodePreprocLetterbox::NodePreprocLetterbox(const std::unordered_map<std::string,std::string>& cfg){
  if (auto it=cfg.find("out_h"); it!=cfg.end()) out_h_=std::stoi(it->second);
  if (auto it=cfg.find("out_w"); it!=cfg.end()) out_w_=std::stoi(it->second);
}

bool NodePreprocLetterbox::process(Packet& p, NodeContext& ctx){
  size_t bytes = (size_t)out_c_*out_h_*out_w_*sizeof(float);
  if (!det_input_.handle.device_ptr || det_input_.handle.bytes < bytes) {
    core::MemoryHandle h{}; ctx.gpu_pool->acquire(h, bytes);
    det_input_.handle = h;
  }
  det_input_.shape = {1,out_c_,out_h_,out_w_};
  // <<< launch fused kernel on ctx.stream >>>  把 p.frame(NV12/GPU) → det_input_
  p.tensors["tensor:det_input"] = det_input_;
  return true;
}
```

## 2) 通用模型节点（ORT/TRT — 单/多输出）

```
// node_model.hpp
#pragma once
#include "interfaces.hpp"
#include "analyzer/interfaces.hpp" // IModelSession
namespace analyzer::ms {
class NodeModel : public INode {
public:
  explicit NodeModel(const std::unordered_map<std::string,std::string>& cfg);
  bool open(NodeContext&) override;
  bool process(Packet& p, NodeContext&) override;
  std::vector<std::string> inputs() const override  { return {in_key_}; }
  std::vector<std::string> outputs() const override { return out_keys_; }
private:
  std::string in_key_ = "tensor:det_input";
  std::vector<std::string> out_keys_ = {"tensor:det_raw"};
  std::shared_ptr<IModelSession> ses_;  // 由 composition_root 注入或在 open 里查 EngineRegistry
  // 这里示例直接留空，实际项目中用 EngineRegistry + model id 取会话
};
}
// node_model.cpp
#include "node_model.hpp"
using namespace analyzer::ms;

NodeModel::NodeModel(const std::unordered_map<std::string,std::string>& cfg){
  if (auto it=cfg.find("in"); it!=cfg.end()) in_key_=it->second;
  if (auto it=cfg.find("outs"); it!=cfg.end()) { /* 解析逗号分隔到 out_keys_ */ }
}
bool NodeModel::open(NodeContext& ctx){
  // 从 ctx.engine_registry 获取/构造 IModelSession（ORT/TRT）
  // ses_ = ...
  return true;
}
bool NodeModel::process(Packet& p, NodeContext&){
  auto it = p.tensors.find(in_key_); if (it==p.tensors.end()) return false;
  std::vector<core::TensorView> outs(out_keys_.size());
  ses_->run(it->second, outs);
  for (size_t i=0;i<outs.size();++i) p.tensors[out_keys_[i]] = outs[i];
  return true;
}
```

## 3) NMS（检测后处理）

```
// node_nms.hpp / .cpp  （读取 tensor:det_raw → 产出 rois:person）
```

## 4) ROI 批处理打包（多阶段关键——把多个 ROI warp 成 N×C×H×W）

```
// node_roi_batch.hpp
#pragma once
#include "interfaces.hpp"
namespace analyzer::ms {
class NodeRoiBatch : public INode {
public:
  explicit NodeRoiBatch(const std::unordered_map<std::string,std::string>& cfg);
  bool process(Packet& p, NodeContext& ctx) override;
  std::vector<std::string> inputs()  const override { return {"rois:person"}; }
  std::vector<std::string> outputs() const override { return {"tensor:roi_nchw"}; }
private:
  int out_h_=256, out_w_=192, out_c_=3, max_rois_=8;
  core::TensorView roi_input_; // N×C×H×W
};
}
// node_roi_batch.cpp
#include "node_roi_batch.hpp"
using namespace analyzer::ms;
NodeRoiBatch::NodeRoiBatch(const std::unordered_map<std::string,std::string>& cfg){
  if (auto it=cfg.find("out_h"); it!=cfg.end()) out_h_=std::stoi(it->second);
  if (auto it=cfg.find("out_w"); it!=cfg.end()) out_w_=std::stoi(it->second);
  if (auto it=cfg.find("max_rois"); it!=cfg.end()) max_rois_=std::stoi(it->second);
}
bool NodeRoiBatch::process(Packet& p, NodeContext& ctx){
  auto it = p.rois.find("rois:person"); if (it==p.rois.end()) return true; // 无ROI则跳过
  auto& rs = it->second;
  int N = (int)std::min((int)rs.size(), max_rois_);
  if (N<=0) return true;
  size_t bytes = (size_t)N*out_c_*out_h_*out_w_*sizeof(float);
  if (!roi_input_.handle.device_ptr || roi_input_.handle.bytes<bytes){
    core::MemoryHandle h{}; ctx.gpu_pool->acquire(h, bytes); roi_input_.handle=h;
  }
  roi_input_.shape = {N,out_c_,out_h_,out_w_};
  // <<< launch roi_warp_affine_kernel on ctx.stream >>> 从 p.frame(NV12) + rs[0..N) 生成 roi_input_
  p.tensors["tensor:roi_nchw"] = roi_input_;
  return true;
}
```

## 5) 关键点解码 / 渲染（同理略）

------

# 在 Analyzer 中使用

你可以做一个薄封装，把这张图作为一个 `IAnalyzer` 落入现管线：

```
// Two lines pseudo
class MultiStageAnalyzer : public IAnalyzer {
public:
  explicit MultiStageAnalyzer(analyzer::ms::Graph g) : g_(std::move(g)) {}
  bool process(const core::FrameSurface& in, core::FrameSurface& out) override {
    analyzer::ms::Packet pkt; pkt.frame = in;
    analyzer::ms::NodeContext ctx{/*stream*/stream_mgr.get(in.source_id), host_pool, gpu_pool, engine_registry, logger};
    bool ok = g_.run(pkt, ctx);
    out = pkt.frame; // OSD节点直接在 NV12 上绘制；或从 pkt.tensors 找到覆盖帧
    return ok;
  }
private:
  analyzer::ms::Graph g_;
};
```

------

# YAML 配置：声明节点 & 边（灵活拓扑）

## 例1：姿态（检测→NMS→ROI打包→姿态→关键点解码→叠加）

```
task: multistage
graph:
  nodes:
    - { id: pre,  type: preproc.letterbox, out_h: 640, out_w: 640 }
    - { id: det,  type: model, in: "tensor:det_input", outs: "tensor:det_raw", model_id: "yolov12x_fp16" }
    - { id: nms,  type: nms, in: "tensor:det_raw", out: "rois:person", conf: 0.25, iou: 0.45, cls: 0 }
    - { id: crop, type: roi.batch, in: "rois:person", out_h: 256, out_w: 192, max_rois: 8 }
    - { id: pose, type: model, in: "tensor:roi_nchw", outs: "tensor:pose_raw", model_id: "hrnet_w32_fp16" }
    - { id: kpt,  type: kpt.decode, in: "tensor:pose_raw", out: "tensors:kpts", K: 17 }
    - { id: osd,  type: overlay.pose, in: "tensors:kpts" }
  edges:
    - { from: pre,  to: det }
    - { from: det,  to: nms }
    - { from: nms,  to: crop }
    - { from: crop, to: pose }
    - { from: pose, to: kpt }
    - { from: kpt,  to: osd }
```

## 例2：多分支（检测后分两路：属性分类 & ReID）

```
graph:
  nodes:
    - { id: pre,   type: preproc.letterbox, out_h: 640, out_w: 640 }
    - { id: det,   type: model, in: "tensor:det_input", outs: "tensor:det_raw", model_id: "yolov12x_fp16" }
    - { id: nms,   type: nms, in: "tensor:det_raw", out: "rois:person", conf: 0.25 }
    - { id: cropA, type: roi.batch, in: "rois:person", out_h: 224, out_w: 224, max_rois: 8 }
    - { id: attr,  type: model, in: "tensor:roi_nchw", outs: "tensor:attr_logits", model_id: "attr_resnet50_fp16" }
    - { id: cropB, type: roi.batch, in: "rois:person", out_h: 256, out_w: 128, max_rois: 8 }
    - { id: reid,  type: model, in: "tensor:roi_nchw", outs: "tensor:embedding", model_id: "reid_osnet_fp16" }
    - { id: osd,   type: overlay.attr_reid, in: "tensor:attr_logits,tensor:embedding" }
  edges:
    - { from: pre,  to: det }
    - { from: det,  to: nms }
    - { from: nms,  to: cropA }
    - { from: nms,  to: cropB }
    - { from: cropA,to: attr }
    - { from: cropB,to: reid }
    - { from: attr, to: osd }
    - { from: reid, to: osd }
```

> 说明：节点 `type` 与 `NodeRegistry` 中注册的类型对应（例如 `"preproc.letterbox"` → `NodePreprocLetterbox`）。新增算法=新增节点类+注册，无需改 Graph/Analyzer。

------

# 执行模型与性能细节

- **单 Packet 贯穿**：默认同帧各节点共享一个 `Packet`，键名区分不同中间结果，避免复制。
- **同一流**：`NodeContext.stream` 来自你的 `GpuRuntime`（每路唯一流），所有 kernel/ORT/TRT enqueue 都发在这条流；无 `cudaDeviceSynchronize`。
- **CUDA Graph（可选）**：分辨率&批形状固定时，`Graph` 提供 `capture()`/`launch()`（你可在 `graph.run()` 首帧捕获、后续重放）。
- **池化**：节点需要的输出缓冲统一从 `GpuBufferPool/HostBufferPool` 获取（已与 ORT IOBinding/Env Allocator 打通），生命周期由 `Packet` 持有/释放。
- **QoS**：沿用你现有 `core::FrameGate` 在外部控制输入节奏；节点内部如 `roi.batch` 决定 `max_rois` 与微批窗口，时延/吞吐可控。

------

# 如何在现工程接入

1. 把上述 `multistage/` 源码加进项目；
2. 在 `composition_root.cpp` 里解析 `graph:` 配置：
   - 调 `NodeRegistry::create(type, node_cfg)` 生成节点；
   - `Graph::add_node()` + `add_edge()` + `compile()`；
   - 用 `MultiStageAnalyzer` 包装成一个 `IAnalyzer`；
3. `PipelineBuilder` 若 `task: multistage`，就使用 `MultiStageAnalyzer`；
4. 每路 `NodeContext` 注入同一 `cudaStream`、池子、引擎仓库（你已有）。

------

# 扩展点（以后要加也简单）

- **条件边/过滤**：给节点 `attrs` 写布尔/分数，Graph 执行时允许节点返回“跳过”，或基于 `attrs` 决定是否走某分支。
- **多输入合并**：做一个 `node_join` 从多个键合并（例如拼接 embedding）。
- **跨帧缓存**：节点内部用小型 `std::deque` 缓存，用 `roi.id/track id` 做 state（如 ReID 滑窗平均）。
- **跨路 super-batch**：可在 `graph.run()` 外层加 2–5ms 聚合窗口，将不同路的 `roi.batch` 合并（吞吐优先场景）。

------

## 小结

- **能做**，而且推荐这样做：一个轻量的 **多阶段 DAG 执行器** + 一组**可插拔节点**。
- 不改你现有系统的边界/接口，仅在 analyzer 层新增 `multistage` 子模块；新增任务=新增节点类+配置。
- 继续保持 **GPU 全链路、零拷贝、单流常驻、可选 CUDA Graph**，并与 ORT/TRT、缓冲池、EngineRegistry 无缝衔接。



示例：

太好了！下面给你一套**可编 + 可跑**的“图构建与注入”样例，覆盖：

- `composition_root` 从 **YAML** 解析 → 构建 **Graph** → 注入 **EngineRegistry** 会话（传给 `node_model`）。
- 3 个**最小节点实现**：预处理(`preproc.letterbox`)、通用模型(`model`)、NMS(`nms`)。
- 一个示例 **graph YAML**（可直接放在 `config/graphs/`）。

> 说明：代码与我们之前的 `analyzer/multistage/*` 抽象保持一致。解析用 `yaml-cpp`（CMake 记得 `find_package(yaml-cpp REQUIRED)` 并链接）。

------

# 1) Graph YAML（示例）

```
config/graphs/pose_topdown.yaml
graph:
  nodes:
    - { id: pre,  type: preproc.letterbox, out_h: 640, out_w: 640, out_c: 3, out_key: "tensor:det_input" }
    - { id: det,  type: model, in: "tensor:det_input", outs: "tensor:det_raw", model_id: "yolov12x_fp16" }
    - { id: nms,  type: nms, in: "tensor:det_raw", out: "rois:person", conf: 0.25, iou: 0.45, cls: 0 }
  edges:
    - { from: pre, to: det }
    - { from: det, to: nms }
```

> 关键键：
>
> - `type` 对应节点注册名（见 NodeRegistry）
> - `model_id` 由 `EngineRegistry` 解析为 `IModelSession`
> - `in/outs/out_key` 对应 `Packet.tensors` 的键名
> - YOLO NMS 例子里仅保留 `cls=0`（person）

------

# 2) YAML→Graph 解析器

```
src/analyzer/multistage/yaml_loader.hpp
#pragma once
#include <string>
#include <unordered_map>
#include <vector>

namespace analyzer::ms {

struct YamlNodeCfg {
  std::string id;
  std::string type;
  std::unordered_map<std::string, std::string> kv; // 其余键值转成字符串
};

struct YamlEdgeCfg { std::string from; std::string to; };

struct YamlGraphCfg {
  std::vector<YamlNodeCfg> nodes;
  std::vector<YamlEdgeCfg> edges;
};

bool load_graph_yaml(const std::string& path, YamlGraphCfg& out, std::string* err = nullptr);

} // namespace analyzer::ms
src/analyzer/multistage/yaml_loader.cpp
#include "yaml_loader.hpp"
#include <yaml-cpp/yaml.h>
#include <sstream>

using namespace analyzer::ms;

static std::string to_string_scalar(const YAML::Node& n) {
  if (n.IsScalar()) return n.as<std::string>();
  std::stringstream ss; ss << n; return ss.str();
}

bool load_graph_yaml(const std::string& path, YamlGraphCfg& out, std::string* err) {
  try {
    YAML::Node root = YAML::LoadFile(path);
    auto g = root["graph"];
    if (!g) { if (err) *err = "missing 'graph'"; return false; }

    auto nodes = g["nodes"];
    auto edges = g["edges"];
    if (!nodes || !nodes.IsSequence()) { if (err) *err = "graph.nodes missing/invalid"; return false; }
    if (!edges || !edges.IsSequence()) { if (err) *err = "graph.edges missing/invalid"; return false; }

    out.nodes.clear(); out.edges.clear();
    for (auto& n : nodes) {
      YamlNodeCfg nc;
      nc.id   = n["id"].as<std::string>();
      nc.type = n["type"].as<std::string>();
      for (auto it = n.begin(); it != n.end(); ++it) {
        auto k = it->first.as<std::string>();
        if (k == "id" || k == "type") continue;
        nc.kv[k] = to_string_scalar(it->second);
      }
      out.nodes.push_back(std::move(nc));
    }
    for (auto& e : edges) {
      out.edges.push_back({e["from"].as<std::string>(), e["to"].as<std::string>()});
    }
    return true;
  } catch (const std::exception& ex) {
    if (err) *err = ex.what();
    return false;
  }
}
```

------

# 3) 三个节点的最小实现（可编可跑）

## 3.1 预处理：`preproc.letterbox`

```
src/analyzer/multistage/node_preproc_letterbox.hpp
#pragma once
#include "interfaces.hpp"

namespace analyzer::ms {

class NodePreprocLetterbox : public INode {
public:
  // cfg: out_h/out_w/out_c/out_key
  explicit NodePreprocLetterbox(const std::unordered_map<std::string,std::string>& cfg);
  bool process(Packet& p, NodeContext& ctx) override;
  std::vector<std::string> outputs() const override { return {out_key_}; }

private:
  int out_h_=640, out_w_=640, out_c_=3;
  std::string out_key_ = "tensor:det_input";
  core::TensorView out_;
};

} // namespace
src/analyzer/multistage/node_preproc_letterbox.cpp
#include "node_preproc_letterbox.hpp"
#include "core/logger.hpp"
// 你已有的 CPU 版本（可选）：#include "analyzer/preproc_letterbox_cpu.hpp"

using namespace analyzer::ms;

NodePreprocLetterbox::NodePreprocLetterbox(const std::unordered_map<std::string,std::string>& cfg){
  if (auto it=cfg.find("out_h"); it!=cfg.end()) out_h_=std::stoi(it->second);
  if (auto it=cfg.find("out_w"); it!=cfg.end()) out_w_=std::stoi(it->second);
  if (auto it=cfg.find("out_c"); it!=cfg.end()) out_c_=std::stoi(it->second);
  if (auto it=cfg.find("out_key"); it!=cfg.end()) out_key_=it->second;
}

bool NodePreprocLetterbox::process(Packet& p, NodeContext& ctx){
  // 简化：此处只演示从 NV12 分配输出Tensor；真实项目用你的 CUDA kernel 做 NV12->NCHW+norm
  const size_t bytes = (size_t)out_c_ * out_h_ * out_w_ * sizeof(float);
  if (!out_.handle.device_ptr || out_.handle.bytes < bytes) {
    core::MemoryHandle h{}; ctx.gpu_pool->acquire(h, bytes);
    out_.handle = h;
  }
  out_.shape = {1, out_c_, out_h_, out_w_};
  // TODO: 调用 CUDA 预处理核，把 p.frame -> out_
  p.tensors[out_key_] = out_;
  return true;
}
```

> 这版是“空壳分配 + TODO Kernel”，你也可以直接调用你已有的 `preproc_letterbox_cuda` 内核。

------

## 3.2 通用模型节点：`model`

```
src/analyzer/multistage/node_model.hpp
#pragma once
#include "interfaces.hpp"
#include "analyzer/interfaces.hpp"     // IModelSession
#include <memory>

namespace analyzer::ms {

class NodeModel : public INode {
public:
  // cfg: in / outs (逗号分隔) / model_id
  explicit NodeModel(const std::unordered_map<std::string,std::string>& cfg);

  bool open(NodeContext& ctx) override;                 // 在这里从 EngineRegistry 取会话
  bool process(Packet& p, NodeContext& ctx) override;

  std::vector<std::string> inputs()  const override { return {in_key_}; }
  std::vector<std::string> outputs() const override { return out_keys_; }

private:
  std::string in_key_ = "tensor:det_input";
  std::vector<std::string> out_keys_ = {"tensor:det_raw"};
  std::string model_id_;
  std::shared_ptr<IModelSession> session_;              // 由 EngineRegistry 注入

  // 复用输出句柄，避免频繁分配
  std::vector<core::TensorView> out_bufs_;
};

} // namespace
src/analyzer/multistage/node_model.cpp
#include "node_model.hpp"
#include "core/logger.hpp"
#include "analyzer/engine_registry.hpp"   // 你的 EngineRegistry 抽象

using namespace analyzer::ms;

static std::vector<std::string> split_csv(const std::string& s){
  std::vector<std::string> v; std::string cur;
  for (char c : s) { if (c==',') { if(!cur.empty()) v.push_back(cur); cur.clear(); } else cur.push_back(c); }
  if (!cur.empty()) v.push_back(cur); return v;
}

NodeModel::NodeModel(const std::unordered_map<std::string,std::string>& cfg){
  if (auto it=cfg.find("in"); it!=cfg.end()) in_key_=it->second;
  if (auto it=cfg.find("outs"); it!=cfg.end()) out_keys_=split_csv(it->second);
  if (auto it=cfg.find("model_id"); it!=cfg.end()) model_id_=it->second;
}

bool NodeModel::open(NodeContext& ctx){
  // 这里“把 EngineRegistry 会话交给 node_model”
  auto* reg = reinterpret_cast<analyzer::EngineRegistry*>(ctx.engine_registry);
  if (!reg) { CORE_LOGE("NodeModel: missing EngineRegistry in NodeContext"); return false; }

  // 由 model_id 查找会话（内部已处理 engine/precision 等）
  session_ = reg->get_or_create(model_id_);  // e.g. model_id = "yolov12x_fp16"
  if (!session_) { CORE_LOGE("NodeModel: get_or_create failed: %s", model_id_.c_str()); return false; }

  // 为输出准备缓存（可在首次 process 时按真实尺寸调整，这里先占位）
  out_bufs_.resize(out_keys_.size());
  return true;
}

bool NodeModel::process(Packet& p, NodeContext& ctx){
  auto it = p.tensors.find(in_key_);
  if (it == p.tensors.end()) { CORE_LOGW("NodeModel: input key '%s' not found", in_key_.c_str()); return false; }

  // 准备输出容器（由 IModelSession 决定输出 shape/bytes；支持 IOBinding 到 out_bufs_）
  out_bufs_.assign(out_keys_.size(), core::TensorView{});

  // 推理（建议 IModelSession::run 支持同一 cudaStream；由 session_ 内部 IOBinding 零拷贝）
  if (!session_->run(it->second, out_bufs_, ctx.stream)) {
    CORE_LOGE("NodeModel: session run failed: %s", model_id_.c_str()); return false;
  }

  // 回填到 Packet
  for (size_t i=0;i<out_keys_.size();++i) {
    if (i < out_bufs_.size()) p.tensors[out_keys_[i]] = out_bufs_[i];
  }
  return true;
}
```

> 这里的关键点：`open()` 从 `NodeContext.engine_registry` 取会话，这就是**把 EngineRegistry 会话交给 node_model** 的注入点。无需 composition_root 额外手工塞。

------

## 3.3 NMS（YOLO 风格，CPU 简化版）

```
src/analyzer/multistage/node_nms.hpp
#pragma once
#include "interfaces.hpp"

namespace analyzer::ms {

class NodeNms : public INode {
public:
  // cfg: in / out / conf / iou / cls
  explicit NodeNms(const std::unordered_map<std::string,std::string>& cfg);
  bool process(Packet& p, NodeContext&) override;
  std::vector<std::string> inputs()  const override { return {in_key_}; }
  std::vector<std::string> outputs() const override { return {out_key_}; }

private:
  std::string in_key_ = "tensor:det_raw";
  std::string out_key_ = "rois:person";
  float conf_thr_ = 0.25f, iou_thr_ = 0.45f;
  int cls_keep_ = -1; // -1 不过滤

  // 简单IOU
  static float iou(const Roi& a, const Roi& b);
};

} // namespace
src/analyzer/multistage/node_nms.cpp
#include "node_nms.hpp"
#include "core/logger.hpp"

using namespace analyzer::ms;

// 简化：TensorView 的 host 回退（真实项目请做 GPU 解码/NMS）
static bool tensor_to_host(const core::TensorView& t, std::vector<float>& host) {
  size_t n = (size_t)t.numel();
  host.resize(n);
  if (t.handle.location == core::MemoryLocation::Host) {
    std::memcpy(host.data(), t.handle.host_ptr, n*sizeof(float));
    return true;
  }
  // fallback 拷贝（确保同步）
  if (!t.handle.device_ptr) return false;
  cudaMemcpy(host.data(), (void*)t.handle.device_ptr, n*sizeof(float), cudaMemcpyDeviceToHost);
  cudaDeviceSynchronize();
  return true;
}

NodeNms::NodeNms(const std::unordered_map<std::string,std::string>& cfg){
  if (auto it=cfg.find("in"); it!=cfg.end()) in_key_=it->second;
  if (auto it=cfg.find("out"); it!=cfg.end()) out_key_=it->second;
  if (auto it=cfg.find("conf"); it!=cfg.end()) conf_thr_=std::stof(it->second);
  if (auto it=cfg.find("iou");  it!=cfg.end()) iou_thr_=std::stof(it->second);
  if (auto it=cfg.find("cls");  it!=cfg.end()) cls_keep_=std::stoi(it->second);
}

float NodeNms::iou(const Roi& a, const Roi& b){
  float xx1 = std::max(a.x1,b.x1), yy1 = std::max(a.y1,b.y1);
  float xx2 = std::min(a.x2,b.x2), yy2 = std::min(a.y2,b.y2);
  float w = std::max(0.f, xx2-xx1), h = std::max(0.f, yy2-yy1);
  float inter = w*h, areaA = (a.x2-a.x1)*(a.y2-a.y1), areaB=(b.x2-b.x1)*(b.y2-b.y1);
  return inter / std::max(1e-6f, areaA+areaB-inter);
}

bool NodeNms::process(Packet& p, NodeContext&){
  auto it = p.tensors.find(in_key_);
  if (it==p.tensors.end()) { CORE_LOGW("NodeNms: input key '%s' not found", in_key_.c_str()); return true; }

  // 假设 YOLO 导出格式为 [N, no]，每行为 (cx,cy,w,h, conf, cls0..clsK)
  std::vector<float> host;
  if (!tensor_to_host(it->second, host)) return false;

  // 从 shape 推断 N & no（此处简化：TensorView.shape 已有）
  auto& shape = it->second.shape; if (shape.size()!=2) { CORE_LOGE("NodeNms: expect [N,no]"); return false; }
  int N = (int)shape[0], no = (int)shape[1];

  // 生成候选框
  std::vector<Roi> cand; cand.reserve(N);
  for (int i=0;i<N;i++){
    const float* r = &host[i*no];
    float cx=r[0], cy=r[1], w=r[2], h=r[3], obj=r[4];
    // 取最大类别
    int best_cls=-1; float best=0.f;
    for (int k=5;k<no;k++){ if (r[k]>best){best=r[k]; best_cls=k-5;} }
    float score = obj*best;
    if (score < conf_thr_) continue;
    if (cls_keep_>=0 && best_cls!=cls_keep_) continue;

    Roi b;
    b.x1 = cx - w*0.5f; b.y1 = cy - h*0.5f;
    b.x2 = cx + w*0.5f; b.y2 = cy + h*0.5f;
    b.score = score; b.cls = best_cls;
    cand.push_back(b);
  }

  // NMS
  std::sort(cand.begin(), cand.end(), [](auto& a, auto& b){ return a.score>b.score; });
  std::vector<Roi> keep;
  for (auto& b : cand){
    bool ok=true; for (auto& k : keep){ if (iou(b,k) > iou_thr_) { ok=false; break; } }
    if (ok) keep.push_back(b);
  }

  p.rois[out_key_] = std::move(keep);
  return true;
}
```

> 为了“可跑”，这里把 Tensor 拉回 Host 做了 NMS；你可以很容易替换成你已有的 CUDA NMS。

------

# 4) 注册节点（NodeRegistry）

`src/analyzer/multistage/registry.hpp`（之前已给，这里只放注册宏用法）

```
// 在各 .cpp 尾部或一个集中 cpp 里注册：
#include "registry.hpp"
#include "node_preproc_letterbox.hpp"
#include "node_model.hpp"
#include "node_nms.hpp"

using namespace analyzer::ms;

MS_REGISTER_NODE("preproc.letterbox", NodePreprocLetterbox);
MS_REGISTER_NODE("model",            NodeModel);
MS_REGISTER_NODE("nms",              NodeNms);
```

> 也可以把这段放进一个专门的 `nodes_common.cpp`，避免 ODR 问题。

------

# 5) composition_root：YAML 解析→构建 Graph→注入 EngineRegistry

`src/composition_root.hpp`（新增接口）

```
#pragma once
#include <memory>
#include <string>
#include "analyzer/interfaces.hpp"           // IAnalyzer
#include "analyzer/multistage/graph.hpp"     // Graph
#include "analyzer/engine_registry.hpp"      // EngineRegistry

struct AppConfig {
  std::string graphs_dir = "config/graphs";
  // ... 其他全局配置（engine 默认、qos 等）
};

// 从 graph_id.yaml 构建多阶段 Analyzer
std::unique_ptr<IAnalyzer> build_analyzer_from_yaml(
    const std::string& graph_id,
    const AppConfig& appcfg,
    analyzer::EngineRegistry& engine_registry);
src/composition_root.cpp
#include "composition_root.hpp"
#include "core/logger.hpp"
#include "analyzer/multistage/yaml_loader.hpp"
#include "analyzer/multistage/graph.hpp"
#include "analyzer/multistage/registry.hpp"
#include "analyzer/multistage/interfaces.hpp"
#include "analyzer/multistage/node_preproc_letterbox.hpp"
#include "analyzer/multistage/node_model.hpp"
#include "analyzer/multistage/node_nms.hpp"
#include "analyzer/interfaces.hpp"            // IAnalyzer
#include <filesystem>

using namespace analyzer::ms;

namespace {
  // 一个简单包装：把 Graph 封装成 IAnalyzer
  class MultiStageAnalyzer final : public IAnalyzer {
  public:
    MultiStageAnalyzer(Graph g, analyzer::EngineRegistry* reg, core::HostBufferPool* h, core::GpuBufferPool* d)
      : g_(std::move(g)), reg_(reg), host_(h), dev_(d) {}

    bool process(const core::FrameSurface& in, core::FrameSurface& out) override {
      Packet pkt; pkt.frame = in;
      NodeContext ctx; 
      ctx.stream = core::GpuRuntime::instance().stream(in.source_id);
      ctx.host_pool = host_; ctx.gpu_pool = dev_; ctx.engine_registry = reg_;
      if (!inited_) { // 首帧 open 一次
        for (auto& n : nodes_) { n->open(ctx); }
        inited_ = true;
      }
      bool ok = g_.run(pkt, ctx);
      out = pkt.frame; // 叠加绘制在原帧上时直接传走
      return ok;
    }

    // 供 root 把 nodes_ 给我（Graph持有拷贝）
    void attach_nodes(const std::vector<NodePtr>& ns){ nodes_ = ns; }

  private:
    Graph g_;
    analyzer::EngineRegistry* reg_;
    core::HostBufferPool* host_;
    core::GpuBufferPool*  dev_;
    bool inited_ = false;
    std::vector<NodePtr> nodes_;
  };
}

std::unique_ptr<IAnalyzer> build_analyzer_from_yaml(
    const std::string& graph_id,
    const AppConfig& appcfg,
    analyzer::EngineRegistry& engine_registry) {

  // 1) 解析 YAML
  const auto path = std::filesystem::path(appcfg.graphs_dir) / (graph_id + ".yaml");
  YamlGraphCfg ycfg; std::string err;
  if (!load_graph_yaml(path.string(), ycfg, &err)) {
    CORE_LOGE("load_graph_yaml failed: %s (%s)", path.string().c_str(), err.c_str());
    return nullptr;
  }

  // 2) 逐个节点实例化（通过注册表）
  Graph g;
  std::vector<NodePtr> created;
  created.reserve(ycfg.nodes.size());

  for (auto& n : ycfg.nodes) {
    NodePtr node = NodeRegistry::inst().create(n.type, n.kv); // cfg: kv map
    int id = g.add_node(node, n.id);
    (void)id;
    created.push_back(node);
  }

  // 3) 连边
  // 构建 name->id 索引（Graph 内部也会存，这里简单使用）
  for (auto& e : ycfg.edges) {
    // 简化：Graph 存的是顺序索引，所以需要找到 index
    int from=-1, to=-1;
    for (int i=0;i<(int)created.size();++i){
      // 这里可以增加 names_ 暴露；为了简单假设 add_node 顺序与 ycfg.nodes 顺序一致，用 id 查
      if (ycfg.nodes[i].id == e.from) from = i;
      if (ycfg.nodes[i].id == e.to)   to   = i;
    }
    if (from<0 || to<0) { CORE_LOGE("edge invalid: %s->%s", e.from.c_str(), e.to.c_str()); return nullptr; }
    g.add_edge(from, to);
  }

  if (!g.compile()) { CORE_LOGE("Graph compile failed (cycle?)"); return nullptr; }

  // 4) 封装成 IAnalyzer（注入 EngineRegistry & BufferPools）
  auto* host_pool = core::global_host_pool; // 你已有的全局池
  auto* gpu_pool  = core::global_gpu_pool;

  auto an = std::make_unique<MultiStageAnalyzer>(std::move(g), &engine_registry, host_pool, gpu_pool);
  an->attach_nodes(created); // 为了在首帧 open() 注入会话
  return an;
}
```

> 这里的注入点：`NodeModel::open(NodeContext&)` 通过 `ctx.engine_registry` 获取 `IModelSession`。composition_root 不需要亲自塞会话，**职责清晰**。

------

# 6) CMake 补充

`CMakeLists.txt`（相关片段）

```
find_package(yaml-cpp REQUIRED)

target_link_libraries(video-analyzer
  PRIVATE
    yaml-cpp
    # 你的其它依赖...
)
```

------

# 7) 使用方式（最小流程）

1. 把示例 `pose_topdown.yaml` 放到 `config/graphs/`。

2. 在你的 REST 控制器里调用：

   ```
   AppConfig acfg; acfg.graphs_dir = "config/graphs";
   auto analyzer = build_analyzer_from_yaml("pose_topdown", acfg, engineRegistry);
   pipelineBuilder.attachAnalyzer(std::move(analyzer)); // 伪代码：把 Analyzer 挂到当前会话流水线
   ```

3. 给请求传入合适的 `model_id`（比如在 YAML 里就是 `yolov12x_fp16`），`EngineRegistry` 内部解析到 TRT/ORT 的会话实例。

4. 跑起来后，日志里能看到 `NodeModel::open` 拿到会话、`NodeNms` 产出 `rois:person`。

------

## 小结

- **图构建**：YAML→`YamlGraphCfg`→`NodeRegistry` 实例化→`Graph::compile/run`。
- **会话注入**：在 **节点 `open()`** 里通过 `NodeContext.engine_registry` 取会话（最佳解耦）。
- **三个节点**提供可编可跑骨架，后续把 CUDA 预处理与 GPU-NMS 替换进去即可获得全 GPU 流。