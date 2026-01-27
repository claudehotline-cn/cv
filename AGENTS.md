# 仓库指南

本文档是该仓库的简明贡献者指南，说明代码库的组织方式，以及如何高效地构建、测试与贡献。

## 1 项目结构与模块划分

- `video-analyzer/` – 核心后端（简称VA）（RTSP 接入、预处理、推理、后处理、WebRTC/HLS 输出）。
- `controlplane` - 控制平面（简称CP）。前端项目只与CP项目交互，CP、VA、VSM之间采用gRPC通信。
- `web-frontend/` – 前端项目，Web 界面，用于预览流与叠加层。
- `video-source-manager/` – 管理 RTSP 源的工具集合（简称VSM）。
- `lro` - long-running operation 通用库。
- `docs/` – 设计笔记、GPU 全链路改造方案与规划、测试指南。
  - `design/` - 项目设计文档
  - `examples/` - 项目示例
  - `plans/` - 项目计划文档
  - `references/` - 项目参考文档
  - `requirements/` - 项目需求文档
  - `memo/` 项目开发备忘录
- `tools/` – 开发脚本（构建/运行、测试辅助）。
- `third_party/` – 外部依赖或内置的第三方代码。
- `db/` - 数据库脚本。
- `logs/` - 项目日志
- `.github` - github action 脚本目录
- `grafana` - grafana 面板设计文档目录

## 2 工作流程

**必须遵守的工作流程**：根据需求修改代码->构建成功->运行程序->测试->提交远程仓库->总结并追加memo
**以上工作流程由AI自动完成。**

## 3 构建

- 后端：
  - 构建前先将后端进程关闭。
  - 确保项目构建成功。
  - 构建脚本位于`D:\Projects\ai\cv\tools`目录下。
  - Windows：`video-analyzer` 项目在 `D:\Projects\ai\cv\video-analyzer\build-ninja` 目录下使用 `D:\Projects\ai\cv\tools\build_va_with_vcvars.cmd` 工具进行构建；`video-source-manager` 项目在 `D:\Projects\ai\cv\video-source-manager\build` 目录下使用`D:\Projects\ai\cv\tools\build_vsm_with_vcvars.cmd` 工具进行构建。
  - Linux/macOS：`cmake -S . -B build && cmake --build build -j`
  - **不要随便清除构建目录，除非我允许**。

## 4 运行

- 在独立进程中启动前后端项目。
- 后端：
  - video-analyzer：`D:\Projects\ai\cv\video-analyzer\build-ninja\bin\VideoAnalyzer.exe D:\Projects\ai\cv\video-analyzer\build-ninja\bin\config`（Windows：选择对应配置子目录）。
  - video-source-manager：`D:\Projects\ai\cv\video-source-manager\build\bin\VideoSourceManager.exe`
- 前端：
  - 在 `D:\Projects\ai\cv\web-front` 目录下，执行 `npm run dev`

## 5 测试

### 5.1 后端：

- 项目构建成功后必须进行测试，不需要询问。
- 可以使用 `d:\Projects\ai\cv\video-analyzer\test\scripts` 下的脚本测试，新编写脚本也放在该目录下。
- 常用目标：`VideoAnalyzer`、`VideoSourceManager`（若已定义）。

### 5.2 前端：

- 使用**playwright mcp**或**chrome devtools mcp**服务操作浏览器进行测试。
- 使用**playwright mcp**时：
  1) 不要调用 browser_snapshot。
  2) 任何截图一律保存为文件且只返回文件路径；禁止内联 base64。
  3) 仅使用这些工具：browser_navigate, browser_click, browser_type, browser_evaluate, browser_tabs。
  4) 优先用 browser_evaluate 精确返回结构化 JSON（最多 10 条关键字段），禁止返回整页 HTML/DOM。
  5) 只有我说要导出 PDF 时，才允许使用与 PDF 相关的能力。
  6) 工具输出必须“最小充分”：不重复、不赘述、不粘贴大文本或二进制。
- 使用**chrome devtools**时：
  你是“最小充分取证”的 Chrome DevTools 代理。你的任务是在最小上下文前提下完成定位与佐证：只取关键数据，先聚合后钻取，所有可视证据以文件路径返回。
  1. 全局硬性约束（必须遵守）

     - 禁止快照类工具：不要调用 dom_snapshot / page_snapshot / html_dump / full_dom_dump（或任何等价能力）。
     - 截图/导出：允许截屏，但必须保存为文件并仅返回文件路径；严禁返回内联 base64。
     - 允许的工具（仅此白名单，名称以实际实现为准）：
       - 导航/页面：page_navigate, page_set_viewport（或等价 emulation 工具）
       - 评估：runtime_evaluate（仅返回结构化 JSON，最多 10 条关键字段）
       - 网络：network_list_requests, network_get_request
       - 控制台：console_list_messages
       - 性能：performance_start_trace, performance_stop_trace
       - 截图：page_screenshot
       - 仿真（可选）：emulation_set_network_conditions, emulation_set_cpu_throttling
       若工具名不同，请映射到上述等价能力；禁止调用不在白名单内的工具。
     - 输出格式：
       - 默认只输出结构化 JSON（对象或数组）。
       - 每类清单最多 10 条；每条最多 10 个关键字段（url/status/method/type/initiator/size/duration/ts/... 等）。
       - 禁止返回整页 HTML、DOM、源码、长日志或大对象。
       - 需要图片/trace 等二进制证据时，保存为文件再返回文件路径与一句话摘要。
     - PDF 能力：只有当我明确要求导出 PDF时，才可使用相关工具；否则禁止。
     - 错误与异常：若工具失败，仅返回 { "error": "<简要原因>", "tool": "`<name>`" }；不要粘贴堆栈。
     - 最小充分：不重复、不赘述、不粘贴大文本或二进制；先统计聚合→再按我要求钻取单条详情。
  2. 默认取证窗口与限额（可被我覆盖）
     - 时间窗：最近 30 秒（网络与控制台）。
     - 清单条数：≤10。
     - 性能 Trace：5–10 秒，仅一次；停止后给关键指标与瓶颈概览（结构化 JSON）。
- 测试 whep 时可使用`chrome://webrtc-internals/`, 可以参考`https://datatracker.ietf.org/doc/draft-ietf-wish-whep/`

- 工具：
  - 需要操作数据库的测试，请使用`C:\Program Files\MySQL\MySQL Shell 8.4\bin\mysqlsh.exe`工具验证数据库中的数据是否正确。
  - 测试视频源：rtsp://192.168.50.78:8554/camera_01
- 测试流程：
  1. 启动 VA 和 VSM 项目;
  2. 使用 netstat 或 curl 检测端口监听或 http 服务可访问；
  3. 使用 **playwright mcp**或**chrome devtools mcp**服务进行测试，或者不需要前端参与的测试使用测试脚本进行测试。
- 测试规范：
  - Python 测试位于 `video-analyzer/test/`。新增用例请与现有脚本放在一起。
  - 脚本命名应具描述性，例如：`check_gpu_inference.py`、`compare_modes.py`。
  - 最低要求：验证处理帧数（>0）且无 HTTP/RTSP 错误。建议增加 FPS 与检测数量的断言。
- 测试环境：
  - 数据库（Mysql）
    - user：root
    - password：123456
    - port：13306
    - host: 192.168.50.78
    - db: cv_cp
  - redis:
    - host: 192.168.50.78

## 6 提交与合并请求规范

- 保证项目构建成功并通过测试后，再提交至远程仓库。
- 提交信息：使用祈使现在时，例如 “Implement GPU IoBinding host staging”。
- 提交信息使用中文。
- 将相关更改归组；保持 diff 聚焦。需要时用 `#id` 关联 Issue。
- 拉取请求需包含：摘要、动机、关键变更、测试证据（日志/截图）与回滚方案。

## 7 代码风格与命名规范

- C++：遵循现有风格（大括号同一行，缩进 2–4 空格；函数/文件优先使用 `snake_case`，类名使用 `CamelCase`）。
- 避免使用单字母标识符；方法保持短小且聚焦；变量名规范且具有描述性。
- 在合适场景使用 `const`、`std::span` 与 `std::string_view`；优先使用 `std::unique_ptr`/`std::shared_ptr` 管理所有权。
- 格式化：与周边文件保持一致；除非要求，请勿新增版权/许可证头。
- 确保代码设计符合开闭原则、里氏替换原则、依赖倒置原则、单一职责等原则。

## 8 面向 Agent 的说明

- 软件设计需满足开闭原则、里氏替换原则、依赖倒置原则、单一职责原则。
- 项目构建成功后必须进行测试，不需要询问。
- 遵循分阶段计划；优先提交最小且定向的补丁。
- 未经方案/负责人确认，不要变更公共接口。
- 新增 GPU 路径时保留 CPU 回退；以选项开关保护特性，并在合并前通过自动化测试验证。
- 修改代码时使用`apply_patch` 工具。
- 如需在 Markdown 文档中画图，请使用 mermaid。
- 每一次任务执行完后，在`docs/memo`目录下使用markdown文件记录,每天一个文件，文件名中包含日期。文件内容，已当前日期+时间开始，然后后面为任务执行情况，每个任务都是这样的格式进行追加；如果有以当前日志命名的文件，在该文件最后进行追加。追加memo不需要询问。

## 9 约束

- 请使用中文与我交流。
- windows 环境下使用 pwsh。

