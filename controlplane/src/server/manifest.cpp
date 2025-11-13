#include "controlplane/manifest.hpp"
#include <yaml-cpp/yaml.h>

namespace controlplane::manifest {

static inline bool has_key(const YAML::Node& n, const char* k) { return n && n[k]; }

CheckResult validate_yaml(const std::string& yaml_text) {
  CheckResult res; res.ok = false; res.code = "MANIFEST_REQUIRED"; res.msg = "manifest is empty";
  if (yaml_text.empty()) return res;
  YAML::Node root;
  try { root = YAML::Load(yaml_text); }
  catch (const std::exception& ex) { res.code = "MANIFEST_INVALID_YAML"; res.msg = ex.what(); return res; }
  catch (...) { res.code = "MANIFEST_INVALID_YAML"; res.msg = "unknown yaml parse error"; return res; }
  // model.task
  if (!has_key(root, "model") || !root["model"]["task"] || !root["model"]["task"].IsScalar()) {
    res.code = "MANIFEST_MISSING_FIELD"; res.msg = "missing model.task"; res.diag = { {"field","model.task"} }; return res;
  }
  // exports.onnx.opset & dtype
  if (!has_key(root, "exports") || !root["exports"]["onnx"]) {
    res.code = "MANIFEST_MISSING_FIELD"; res.msg = "missing exports.onnx"; res.diag = { {"field","exports.onnx"} }; return res;
  }
  auto onnx = root["exports"]["onnx"];
  if (!onnx["opset"] || !(onnx["opset"].IsScalar() || onnx["opset"].IsSequence())) {
    res.code = "MANIFEST_MISSING_FIELD"; res.msg = "missing exports.onnx.opset"; res.diag = { {"field","exports.onnx.opset"} }; return res;
  }
  // normalize opset (allow sequence for multi-opset; pick first)
  int opset = 0;
  try {
    if (onnx["opset"].IsScalar()) opset = onnx["opset"].as<int>(0);
    else if (onnx["opset"].IsSequence() && onnx["opset"].size()>0) opset = onnx["opset"][0].as<int>(0);
  } catch (...) { opset = 0; }
  if (opset <= 0) { res.code = "MANIFEST_INVALID_VALUE"; res.msg = "exports.onnx.opset must be positive"; res.diag = { {"field","exports.onnx.opset"} }; return res; }
  // dtype
  std::string dtype;
  if (onnx["dtype"]) try { dtype = onnx["dtype"].as<std::string>(""); } catch (...) {}
  if (dtype.empty()) dtype = "fp32"; // default tolerance
  {
    std::string d = dtype; for (auto& c : d) c = (char)tolower((unsigned char)c);
    if (!(d=="fp32" || d=="fp16" || d=="int8")) { res.code="MANIFEST_UNSUPPORTED_DTYPE"; res.msg="unsupported dtype"; res.diag={{"field","exports.onnx.dtype"},{"value",dtype}}; return res; }
  }
  // io.inputs[*].name/shape; io.outputs[*].name
  if (!has_key(root, "io") || !root["io"]["inputs"] || !root["io"]["inputs"].IsSequence() || root["io"]["inputs"].size()==0) {
    res.code = "MANIFEST_IO_MISSING"; res.msg = "missing io.inputs"; res.diag = { {"field","io.inputs"} }; return res;
  }
  for (auto it : root["io"]["inputs"]) {
    if (!it["name"] || !it["name"].IsScalar()) { res.code="MANIFEST_IO_MISSING"; res.msg="io.inputs[].name required"; res.diag={{"field","io.inputs[].name"}}; return res; }
    if (!it["shape"] || !(it["shape"].IsSequence() || it["shape"].IsScalar())) { res.code="MANIFEST_IO_MISSING"; res.msg="io.inputs[].shape required"; res.diag={{"field","io.inputs[].shape"}}; return res; }
  }
  if (!root["io"]["outputs"] || !root["io"]["outputs"].IsSequence() || root["io"]["outputs"].size()==0) {
    res.code = "MANIFEST_IO_MISSING"; res.msg = "missing io.outputs"; res.diag = { {"field","io.outputs"} }; return res;
  }
  for (auto it : root["io"]["outputs"]) {
    if (!it["name"] || !it["name"].IsScalar()) { res.code="MANIFEST_IO_MISSING"; res.msg="io.outputs[].name required"; res.diag={{"field","io.outputs[].name"}}; return res; }
  }
  // If reached here, basic checks OK
  res.ok = true; res.code = "OK"; res.msg = ""; return res;
}

} // namespace controlplane::manifest

