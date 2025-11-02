### 架构调整说明

**背景**
 现有架构中，LRO（Leo）用于管理长时间任务的生命周期，如创建、监控、取消、状态管理等，而**视频分析（VA）层**需要处理高效的 GPU 计算任务（如预处理、推理），目前面临以下问题：

1. **上下文管理问题**：多个执行线程（例如处理预处理、推理的线程）之间的 CUDA 上下文和设备不一致，导致 GPU 路径失败。
2. **资源调度问题**：LRO 需要调度不同类型的任务，而 GPU 任务的特殊性（涉及 CUDA 上下文、流管理、显存分配等）使得它与其他任务（如 I/O、CPU 密集型任务）必须有所区分。
3. **架构耦合问题**：当前 LRO 与 VA GPU 任务耦合较紧，GPU 资源管理直接影响 LRO 调度的通用性。

**目标**

- 解决 **GPU 上下文切换不一致**的问题，确保每个线程在执行时能够正确初始化 CUDA 环境。
- 通过 **HookedExecutor** 实现 GPU 任务的调度与管理，确保线程生命周期内的资源管理不影响 LRO 的通用性。
- 通过 **Primary Context（主上下文）** 统一管理 GPU 上下文，消除线程间的上下文切换问题。
- 保持 LRO 作为一个 **通用的任务调度框架**，不直接嵌入 GPU 相关的上下文管理逻辑。

------

### 1. 架构设计（C + B）

#### **C：统一使用 Primary Context（主上下文）**

使用主上下文的最大优点是避免了每次任务执行时都要进行上下文切换，从而提高了性能并简化了代码。所有 GPU 任务（例如预处理、推理）将共享相同的 CUDA 上下文，无需每次显式切换 `CUcontext`。

**Primary Context 配置**
 在 FFmpeg 与 NVDEC 初始化时，使用 **主上下文**：

```
// 在 FFmpeg 的 hwcontext_cuda 初始化时，选择 Primary Context（不需要推送 CUDA 上下文）
AVBufferRef *device_ref = nullptr;
av_hwdevice_ctx_create(&device_ref, AV_HWDEVICE_TYPE_CUDA, nullptr, nullptr, 0);
// 无需使用 cuCtxPushCurrent() 和 cuCtxPopCurrent()，CUDA 上下文会自然传递给不同线程。
```

- **Primary Context** 会使得 CUDA 设备资源（例如显存、流、事件）在不同线程间共享，简化跨线程同步问题。
- 在这种配置下，我们只需要在初始化时调用 `cudaSetDevice(device_id)`，而不再显式进行上下文推送/弹出。

------

#### **B：创建 GPU 线程执行器适配器**

为了保证每个任务在执行时能够在正确的上下文中工作，我们需要在 VA 层创建一个 **GPU 执行器适配器**，将线程的生命周期管理（例如初始化 CUDA 上下文和流）集中化。

- **执行器适配器（ExecutorAdapter）**：该适配器会在每个工作线程启动时调用 `thread_init`，初始化 CUDA 环境，并在线程销毁时清理资源。
- **线程池调度**：通过 `HookedExecutor`，将不同类型的任务（IO、GPU、CPU）分配到不同的执行器，从而避免任务之间的相互干扰。

```
// va/exec/hooked_executor.hpp
#include <lro/executors.h>
#include <cuda_runtime.h>
#include <atomic>

struct ExecutorOptions {
  std::function<void()> thread_init;   // 线程初始化：例如 CUDA 初始化
  std::function<void()> thread_fini;   // 线程销毁：例如 资源释放
};

class HookedExecutor {
public:
  HookedExecutor(size_t workers, size_t maxQueue, ExecutorOptions opt)
      : maxQueue_(maxQueue), thread_init_(std::move(opt.thread_init)), thread_fini_(std::move(opt.thread_fini)) {
    for (size_t i = 0; i < workers; ++i) {
      workers_.emplace_back([this] { worker(); });
    }
  }

  ~HookedExecutor() { stop(); }

  void submit(std::function<void()> fn) {
    std::unique_lock<std::mutex> lk(m_);
    q_.push(std::move(fn));
    cv_.notify_one();
  }

  void stop() {
    bool expected = false;
    if (!stopping_.compare_exchange_strong(expected, true)) return;
    cv_.notify_all();
    for (auto& t : workers_) {
      if (t.joinable()) t.join();
    }
  }

private:
  void worker() {
    if (thread_init_) thread_init_();  // 线程启动时初始化 CUDA 等
    while (!stopping_.load()) {
      std::function<void()> fn;
      {
        std::unique_lock<std::mutex> lk(m_);
        cv_.wait(lk, [this] { return stopping_.load() || !q_.empty(); });
        if (stopping_.load()) break;
        fn = std::move(q_.front());
        q_.pop();
      }
      try {
        fn();
      } catch (...) {
        // 捕获异常，避免线程崩溃
      }
    }
    if (thread_fini_) thread_fini_();  // 线程销毁时清理资源
  }

  size_t maxQueue_;
  std::vector<std::thread> workers_;
  std::queue<std::function<void()>> q_;
  std::mutex m_;
  std::condition_variable cv_;
  std::atomic<bool> stopping_{false};

  std::function<void()> thread_init_;   // 初始化
  std::function<void()> thread_fini_;   // 销毁
};
```

### 2. 实现方案

#### **执行器适配器实例化（在 VA 层）**

在 VA 层创建 GPU 执行器，注入 `thread_init` 和 `thread_fini` 逻辑。

```
// va/exec/gpu_executor.cpp
#include "utils/cuda_tls.hpp"
#include "va/exec/hooked_executor.hpp"

ExecutorOptions gpuExecutorOptions{
  .thread_init = []() {
    // 线程初始化：设置设备，确保 CUDA 环境初始化
    ensure_cuda_ready(0);  // 根据配置的 GPU 设备 ID 设置
  },
  .thread_fini = []() {
    // 线程销毁时做一些资源清理（如果有需要）
  }
};

HookedExecutor gpuExecutor(4, 256, gpuExecutorOptions);  // 4个GPU工作线程
```

#### **GPU 任务调度（提交任务）**

在 VA 层的 GPU 任务中，使用适配器来提交任务。

```
// va/preproc/preproc_cuda.cpp
#include "va/exec/gpu_executor.hpp"
#include "utils/cuda_ctx_guard.hpp"

bool PreprocCUDA::run(const Frame& f, TensorView& out, Meta& m) {
  ensure_cuda_ready(f.device.device_id);  // 保证设备已初始化
  CudaCtxGuard g(f.device.cu_ctx);       // 切换到正确的 CUDA 上下文
  
  // 提交任务到 GPU 执行器
  gpuExecutor.submit([&]{
    // 处理预处理任务：memcpyAsync / kernel 执行等
  });
  
  return true;
}
```

### 3. Primary Context 配置（路径 C）

确保 FFmpeg/NVDEC 使用主上下文，在 FFmpeg 配置中设置主上下文。

```
// 在 FFmpeg 的 hwcontext_cuda 初始化时，选择 Primary Context（不需要推送 CUDA 上下文）
AVBufferRef *device_ref = nullptr;
av_hwdevice_ctx_create(&device_ref, AV_HWDEVICE_TYPE_CUDA, nullptr, nullptr, 0);
// 无需使用 cuCtxPushCurrent() 和 cuCtxPopCurrent()，CUDA 上下文会自然传递给不同线程。
```

### 4. 资源与同步管理：`StreamPool` 和 `Event`

#### **`StreamPool`（线程私有的 CUDA 流池）**

```
// va/exec/stream_pool.hpp
#include <cuda_runtime.h>
#include <thread>
#include <unordered_map>

class StreamPool {
public:
  static StreamPool& instance() {
    static StreamPool pool;
    return pool;
  }

  cudaStream_t tls() {
    std::thread::id this_id = std::this_thread::get_id();
    auto& stream = pool_[this_id];
    if (!stream) {
      cudaStreamCreate(&stream);
    }
    return stream;
  }

private:
  std::unordered_map<std::thread::id, cudaStream_t> pool_;
};
```

#### **事件同步**

对于 GPU 任务之间的依赖（例如预处理与推理），通过 `cudaEvent` 进行同步。

```
// 使用 cudaEvent 来同步任务
cudaEvent_t event;
cudaEventCreate(&event);
cudaEventRecord(event, streamA);
cudaStreamWaitEvent(streamB, event, 0);  // 等待 streamA 完成
```

------

### 5. 完整的 LRO 与 GPU 结合

```
// 在 VA 侧，将 `Step::Class` 拆分并映射到 GPU 执行器
lro::Runner runner(cfg);
runner.addStep(lro::Step{"preproc", [&](std::shared_ptr<lro::Operation>& op) {
  PreprocCUDA preproc;
  preproc.run(op->getFrame(), op->output(), op->meta());  // 这里 preproc.run 会提交任务给 gpuExecutor
}});
```

------

### 总结

**C + B 组合方案**为当前架构提供了非常优雅的解决方式：

1. **Primary Context** 解决了 CUDA 上下文管理的问题，避免了每次任务中显式切换 `CUcontext`，提高了性能并简化了代码。
2. **GPU 执行器适配器**（`HookedExecutor`）确保了每个线程的 CUDA 环境初始化和资源清理工作被正确地管理，同时不影响 Leo 的通用性。
3. 通过 **StreamPool** 和 **事件同步** 进一步优化了 GPU 流和任务的并行度，避免了任务之间的资源冲突。

在此基础上，现有架构可以无缝集成 GPU 任务管理，同时保持 LRO 作为通用任务调度框架的独立性和通用性。
