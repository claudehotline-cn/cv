# 仓库指南

本文档是该仓库的简明贡献者指南，说明代码库的组织方式，以及如何高效地构建、测试与贡献。

## 项目结构与模块划分

- `video-analyzer/` – 核心后端（RTSP 接入、预处理、推理、后处理、WebRTC/HLS 输出）。
- `web-frontend/` – Web 界面，用于预览流与叠加层。
- `video-source-manager/` – 管理 RTSP 源的工具集合。
- `docs/` – 设计笔记、GPU 全链路改造方案与规划、测试指南。
  - `design/` - 项目设计文档
  - `examples/` - 项目示例
  - `plans/` - 项目计划文档
  - `references/` - 项目参考文档
  - `requirements/` - 项目需求文档
- `tools/` – 开发脚本（构建/运行、测试辅助）。
- `third_party/` – 外部依赖或内置的第三方代码。
- `db/` - 数据库脚本。
- `logs/` - 项目日志

## 构建、测试与开发命令

- 构建（CMake，源外构建）：
  - 构建前先将后端进程关闭。
  - 确保项目构建成功。
  - Windows：`video-analyzer` 项目在 `D:\Projects\ai\cv\video-analyzer\build-ninja` 目录下使用 `D:\Projects\ai\cv\tools\build_with_vcvars.cmd` 工具进行构建；`video-source-manager` 项目在 `D:\Projects\ai\cv\video-source-manager\build` 目录下构建。
  - Linux/macOS：`cmake -S . -B build && cmake --build build -j`
- 运行：
  - 后端：
    - video-analyzer：`D:\Projects\ai\cv\video-analyzer\build-ninja\bin\VideoAnalyzer.exe D:\Projects\ai\cv\video-analyzer\build-ninja\bin\config`（Windows：选择对应配置子目录）。
    - video-source-manager：`D:\Projects\ai\cv\video-source-manager\build\bin\VideoSourceManager.exe`
- 测试：
  - 项目构建成功后必须进行测试，不需要询问。
  - 可以使用 `d:\Projects\ai\cv\video-analyzer\test\scripts` 下的脚本测试，新编写脚本也放在该目录下。
  - 常用目标：`VideoAnalyzer`、`install`、`package`（若已定义）。
  - 前端测试：使用**playwright mcp**服务操作浏览器进行测试。
  - 需要操作数据库的测试，请使用`mysqlsh`工具验证数据库中的数据是否正确。

## 代码风格与命名规范

- C++：遵循现有风格（大括号同一行，缩进 2–4 空格；函数/文件优先使用 `snake_case`，类名使用 `CamelCase`）。
- 避免使用单字母标识符；方法保持短小且聚焦。
- 在合适场景使用 `const`、`std::span` 与 `std::string_view`；优先使用 `std::unique_ptr`/`std::shared_ptr` 管理所有权。
- 格式化：与周边文件保持一致；除非要求，请勿新增版权/许可证头。
- 确保代码设计符合开闭原则、里氏替换原则、依赖倒置原则、单一职责原则。

## 测试规范

- Python 测试位于 `video-analyzer/test/`。新增用例请与现有脚本放在一起。
- 脚本命名应具描述性，例如：`check_gpu_inference.py`、`compare_modes.py`。
- 最低要求：验证处理帧数（>0）且无 HTTP/RTSP 错误。建议增加 FPS 与检测数量的断言。

## 提交与合并请求规范

- 保证项目构建成功并通过测试后，再提交至远程仓库。
- 提交信息：使用祈使现在时，例如 “Implement GPU IoBinding host staging”。
- 提交信息使用中文。
- 将相关更改归组；保持 diff 聚焦。需要时用 `#id` 关联 Issue。
- 拉取请求需包含：摘要、动机、关键变更、测试证据（日志/截图）与回滚方案。

## 面向 Agent 的说明

- 软件设计需满足开闭原则、里氏替换原则、依赖倒置原则、单一职责原则。
- 遵循分阶段计划；优先提交最小且定向的补丁。
- 未经方案/负责人确认，不要变更公共接口。
- 新增 GPU 路径时保留 CPU 回退；以选项开关保护特性，并在合并前通过自动化测试验证。
- 修改代码时使用`apply_patch` 工具。
- 如需在 Markdown 文档中画图，请使用 mermaid。
- 上下文窗口≤5%时，将当前对话的关键信息在`docs/context`目录下重新生成一个CONTEXT.md文档；在相同目录下使用`roadmap`自定义命令重新生成一个ROADMAP.md文档。
- 每一次任务执行完后，在`docs/memo`目录下使用markdown文件记录,每天一个文件，文件名中包含日期。文件内容，已当前日期+时间开始，然后后面为任务执行情况，每个任务都是这样的格式进行追加。追加memo不需要询问。

## 约束

- 请使用中文与我交流。
