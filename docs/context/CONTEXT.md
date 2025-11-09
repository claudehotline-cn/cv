# CONTEXT（In-Process Triton + MinIO 迁移与修复纪要）

## 背景
- 组件：`video-analyzer` 以内嵌（In-Process）方式集成 Triton（`libtritonserver`），并计划将模型仓库迁移到 MinIO（S3 兼容）。
- 相关代码与配置：
  - 源码：`video-analyzer/src/analyzer/triton_inproc_session.cpp|.hpp`、`triton_inproc_server_host.cpp|.hpp`
  - Compose：`docker/compose/docker-compose.yml`、`docker/compose/docker-compose.gpu.override.yml`
  - 运行配置：`docker/config/va/app.yaml`
  - 设计文档：`docs/design/minio_s3_model_repository.md`

## 主要问题与修复
1) 编译失败
- 现象：`TRITONSERVER_InferenceRequestSetBatchSize` 未声明。
- 根因：所用 Triton 头文件无该 API（或已废弃）。
- 修复：删除该调用，批次由输入张量形状推断；保留“assume_no_batch 时去掉前导 1 维”。

2) In-Process 推理段错误
- 现象：调用 `ServerInferAsync` 后崩溃。
- 根因：异步入队后仍手动 `InferenceRequestDelete` 触发双重释放；释放回调签名不匹配（需三参）。
- 修复：
  - 使用 `TRITONSERVER_InferenceRequestSetReleaseCallback(req, fn(TRITONSERVER_InferenceRequest*, unsigned int, void*), userp)`；
  - 入队成功后不再手动删除 request，仅在早期失败分支清理；
  - 保留输出分配器（GPU 优先，CPU 回退）。

3) 每帧后出现 30s 关停等待日志
- 现象：打印“Waiting for in-flight requests… Timeout 30…”。
- 根因：`TritonInprocServerHost` 仅被临时 `shared_ptr` 持有，`run()` 返回即析构，触发 `TRITONSERVER_ServerDelete`。
- 修复：会话内持有 `shared_ptr<TritonInprocServerHost>` 成员，保证会话生命周期内 Server 常驻；移除会话析构时卸载模型的逻辑（避免误卸载）。

## MinIO（S3）模型仓库集成
- Compose 新增服务：`minio`（9000/9001）与 `minio-mc`（初始化桶 `cv-models`，带健康检查与等待）。
- VA 注入环境变量（同时支持多种解析路径）：
  - `AWS_ACCESS_KEY_ID/SECRET`, `AWS_REGION/AWS_DEFAULT_REGION`, `AWS_EC2_METADATA_DISABLED=true`
  - `AWS_ENDPOINT_URL`, `AWS_ENDPOINT_URL_S3`, `AWS_S3_ENDPOINT`, `AWS_S3_FORCE_PATH_STYLE=true`
  - `S3_ACCESS_KEY_ID/SECRET`, `S3_REGION`, `S3_ENDPOINT`, `S3_USE_HTTPS=0`, `S3_VERIFY_SSL=0`, `S3_ADDRESSING_STYLE=path`, `S3_FORCE_PATH_STYLE=1`
- VA 配置 `triton_repo`：为兼容 In-Process 构建对端点解析差异，采用内嵌端点 URL：
  - `s3://http://minio:9000/cv-models/models`
- 代码中增加最小调试日志打印 repo/endpoint/region，定位便捷。

## 容器内连通性与凭据验证
- 健康检查：`GET http://minio:9000/minio/health/ready` 返回 200。
- S3 签名（容器内 AK/SK）：
  - `PUT /cv-models` → 200（桶创建成功）；
  - `GET /cv-models?list-type=2&prefix=models/` → 200（KeyCount=0）。
- 结论：网络/凭据/签名链路正常；此前报错主要因“桶不存在/端点解析差异”。

## 当前状态
- In-Process 推理稳定；不会因会话生命周期导致 Server 频繁销毁。
- MinIO 作为 S3 模型仓库已打通；可按 `models/<name>/<ver>/model.onnx` 上传并通过 `triton_model(_version)` 指定。
- 所有变更已提交并推送至远程分支 `IOBinding`。

## 后续建议
- 如需更精细诊断，可临时加 `AWS_LOG_LEVEL=debug` 观察 AWS SDK 端点与区域解析。
- 控制平面可提供“Load/Unload/切换版本”接口，`model_control=explicit` 下实现无停机切换；或开启仓库轮询。
- 生产建议开启 MinIO TLS（`S3_USE_HTTPS=1`, `S3_VERIFY_SSL=1`，挂载 CA）。

