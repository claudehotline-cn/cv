# 项目上下文与会话要点（重建版）

本文汇总本轮会话的关键信息，覆盖代码布局、构建与运行、接口与数据库、WHEP/前端调试，以及仍未解决的问题与下一步计划。最后更新时间：2025-10-29。

## 1. 目标与范围
- 目标
  - 用 Chrome DevTools 调试前端分析页的视频播放，验证“CP 代理 VA 实现 WHEP 协商”。
  - 在 CP 中实现并打通三个只读接口：`GET /api/models`、`GET /api/pipelines`、`GET /api/graphs`，从数据库读取数据。
- 模块与交互
  - `controlplane`（CP）：对外 REST；与 `video-analyzer`（VA）、`video-source-manager`（VSM）以 gRPC 通信；反向代理 WHEP。
  - `web-frontend`：仅与 CP 交互；开发期使用 Vite 代理降低 CORS 复杂度。
  - `video-analyzer`（VA）：RTSP 接入、推理、WHEP/HLS 输出；提供 Watch 流转为 CP 的 SSE。
  - `video-source-manager`（VSM）：RTSP 源管理。

## 2. 当前状态（已完成）
- CP 构建：使用 `tools/build_controlplane_with_vcvars.cmd` 生成 `controlplane/build/bin/controlplane.exe`；修复了缺失源码导致的构建/链接问题。
- 路由与基础设施：
  - 新增占位接口：`/api/models|/pipelines|/graphs` 初期返回 `{ "code":"OK", "data": [] }` 保证前端不报错。
  - 全局 CORS 与 `OPTIONS` 预检统一处理。
  - `/whep` 反向代理 VA，并重写 `Location` 到 CP 域。
  - `GET /api/subscriptions/{id}/events`：VA Watch → SSE，含心跳，传递 `phase`。
- 前端开发：开发期 base 使用相对路径或 Vite 代理，避免 CORS；接口统一走 CP。

## 3. 数据库对接（焦点）
- 连接参数（提供方确认“有数据”）
  - host: `127.0.0.1`，port: `13306`，user: `root`，password: `123456`，db: `cv_cp`。
  - `mysqlsh` 侧观测：`models≈5`、`pipelines≈4`、`graphs≈3`。
- 驱动与优先级（遵循“使用经典 / 按 VA 的方式来”）
  1) Classic MySQL Connector/C++（优先）：使用本仓库 `third_party/mysql-connector-c++-9.4.0-winx64`。
     - 运行期依赖：`mysqlcppconn-10-vs14.dll`、`libssl-3-x64.dll`、`libcrypto-3-x64.dll`。
     - 可复用 VA 构建产物中的 DLL：`video-analyzer\build-ninja\bin\mysqlcppconn-10-vs14.dll`、`video-analyzer\build-ninja\bin\mysqlcppconnx-2-vs14.dll`（按需），可拷贝到 CP 可执行目录。
     - 连接属性建议：`allowPublicKeyRetrieval=true`（或同义属性）、`OPT_CONNECT_TIMEOUT`、必要时启用 SSL。
  2) ODBC（备选）：需安装 MySQL/MariaDB 64 位 ODBC 驱动。
  3) MySQL X DevAPI（备选）：需开启 MySQL X Plugin。
- 现象与推断
  - 三接口当前返回空数组，说明 Classic/ODBC/X 三层均未成功查询（异常被兜底为空）。
  - 高概率因认证插件（`caching_sha2_password`）、RSA 公钥获取或运行期 DLL 缺失导致 Classic 连接失败。

## 4. 构建、运行与测试
- 构建（Windows）
  - CP：`tools\build_controlplane_with_vcvars.cmd`（构建前先结束正在运行的 CP 进程）。
  - VA：`tools\build_va_with_vcvars.cmd`（目录：`video-analyzer\build-ninja`）。
  - VSM：`tools\build_vsm_with_vcvars.cmd`（目录：`video-source-manager\build`）。
- 运行
  - VA：`video-analyzer\build-ninja\bin\VideoAnalyzer.exe ...\config`（选择配置子目录）。
  - VSM：`video-source-manager\build\bin\VideoSourceManager.exe`。
  - 前端：`web-front` 目录执行 `npm run dev`。
- 测试流程与要点
  1) 启动 VA 与 VSM；用 netstat/curl 检查端口与 HTTP 健康。
  2) 用 `mysqlsh` 校验 `cv_cp` 各表非空；验证连接参数可用。
  3) 验证 `GET /api/models|/pipelines|/graphs`：期望 200 且 `data` 非空。
  4) 前端分析页：观察 SSE `phase=ready`，WHEP `POST`/`ICE PATCH` 序列，`<video>` 出现 `loadedmetadata/playing`；截图以文件形式保存做证据。
  5) 测试视频源：`rtsp://127.0.0.1:8554/camera_01`。

## 5. 待解决与下一步
- 在 CP 增加最小诊断：捕获 `sql::SQLException`，记录 `errorCode` 与 `what`，或提供 `/api/_debug/db` 汇总三查询的结果/错误。
- 校验 Classic 9.x 属性名是否匹配（`allowPublicKeyRetrieval`/`OPT_GET_SERVER_PUBLIC_KEY` 等）。
- 确保运行期 DLL 就位；若仍失败，短期启用 ODBC 验证路径；必要时启用 MySQL X 方案。
- 精简 `controlplane/CMakeLists.txt` 与 `config/app.yaml` 的重复 DB 配置，避免混淆。

## 6. 目录与关键文件
- 目录：`video-analyzer/`、`controlplane/`、`video-source-manager/`、`web-frontend/`、`docs/`、`tools/`、`third_party/`、`db/`。
- 关键文件
  - `controlplane/src/server/main.cpp`：路由、CORS、WHEP 代理、SSE。
  - `controlplane/src/server/db.cpp`、`include/controlplane/db.hpp`：DB 查询与多驱动兜底。
  - `controlplane/config/app.yaml`：VA/VSM/DB 配置。
  - `third_party/mysql-connector-c++-9.4.0-winx64`：Classic 驱动与头/库/DLL。
  - `video-analyzer/build-ninja/bin/*.dll`：可复用的运行期依赖。

