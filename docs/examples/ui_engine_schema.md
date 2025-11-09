## 引擎表单 Schema 接口（P5）

- Endpoint: `GET /api/ui/schema/engine`
- 返回：JSON（包含字段列表、类型、默认值、说明），便于前端直接渲染表单。

示例返回：
```
{
  "code": "OK",
  "data": {
    "title": "EngineOptionsSchema",
    "version": 1,
    "fields": [
      {"key":"provider", "type":"enum", "default":"triton", "enum":["tensorrt","cuda","cpu","triton"], "help":"推理提供方"},
      {"key":"device", "type":"int", "default":"0", "help":"GPU 设备号（若适用）"},
      {"key":"warmup_runs", "type":"string", "default":"auto", "help":"预热次数（auto/-1=1 次；0=禁用；或整数）"},
      {"key":"triton_inproc", "type":"bool", "default":"true", "help":"启用 In-Process Triton 嵌入"},
      {"key":"triton_repo", "type":"string", "default":"s3://http://minio:9000/cv-models/models", "help":"模型仓库 URL（支持 MinIO）"},
      {"key":"triton_model", "type":"string", "default":"ens_det_trt_full", "help":"模型名称（可为 Ensemble）"},
      {"key":"triton_model_version", "type":"string", "default":"", "help":"模型版本（空=latest）"},
      {"key":"triton_enable_grpc", "type":"bool", "default":"false", "help":"暴露 gRPC 端口（便于 perf_analyzer）"},
      {"key":"triton_enable_http", "type":"bool", "default":"false", "help":"暴露 HTTP 端口（便于 perf_analyzer）"},
      {"key":"triton_backend_dir", "type":"string", "default":"", "help":"后端目录（留空走默认/环境）"},
      {"key":"triton_pinned_mem_mb", "type":"int", "default":"256", "help":"Pinned 内存池大小（MB）"},
      {"key":"triton_cuda_pool_device_id", "type":"int", "default":"0", "help":"CUDA 内存池设备号"},
      {"key":"triton_cuda_pool_bytes", "type":"string", "default":"268435456", "help":"CUDA 内存池字节数（字符串避免溢出）"},
      {"key":"triton_backend_configs", "type":"string", "default":"tensorrt:coalesce_request_input=1", "help":"后端参数，分号分隔，如 backend:key=value"},
      {"key":"triton_gpu_input", "type":"bool", "default":"true", "help":"输入走 GPU 直通（In-Process）"},
      {"key":"triton_gpu_output", "type":"bool", "default":"true", "help":"输出走 GPU 直通（In-Process）"}
    ]
  }
}
```

