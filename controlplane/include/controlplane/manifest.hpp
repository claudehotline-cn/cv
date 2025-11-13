#pragma once
#include <string>
#include <nlohmann/json.hpp>

namespace controlplane::manifest {

struct CheckResult {
  bool ok{false};
  std::string code;   // e.g., MANIFEST_REQUIRED|MANIFEST_INVALID_YAML|MANIFEST_MISSING_FIELD|MANIFEST_UNSUPPORTED_DTYPE
  std::string msg;    // human-friendly message
  nlohmann::json diag; // optional structured diagnostics
};

// Validate a model manifest (YAML text). Performs最小必要校验：
// - 顶层：model.task, exports.onnx.opset, exports.onnx.dtype, io.inputs[*].name/shape, io.outputs[*].name
// - 类型与取值：opset 为正整数；dtype ∈ {fp32,fp16,int8}；shape 为数组
// 返回 CheckResult；ok=false 时包含 code/msg/diag。
CheckResult validate_yaml(const std::string& yaml_text);

} // namespace controlplane::manifest

