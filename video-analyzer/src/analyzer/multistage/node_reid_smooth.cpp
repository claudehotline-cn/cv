#include "analyzer/multistage/node_reid_smooth.hpp"
#include "analyzer/multistage/nodes_common.hpp"
#include "core/logger.hpp"
#include <algorithm>
#include <cmath>
#include <cstring>

using va::analyzer::multistage::util::get_or;
using va::analyzer::multistage::util::get_or_int;
using va::analyzer::multistage::util::split_csv;

namespace va { namespace analyzer { namespace multistage {

NodeReidSmooth::NodeReidSmooth(const std::unordered_map<std::string,std::string>& cfg) {
    if (auto it = cfg.find("in"); it != cfg.end()) in_key_ = it->second;
    if (auto it = cfg.find("out"); it != cfg.end()) out_key_ = it->second;
    if (auto it = cfg.find("id_attr"); it != cfg.end()) id_attr_ = it->second;
    if (auto it = cfg.find("method"); it != cfg.end()) {
        std::string m = it->second; std::transform(m.begin(), m.end(), m.begin(), [](unsigned char c){return (char)std::tolower(c);} );
        method_ = (m=="mean" ? Method::MEAN : Method::EMA);
    }
    if (auto it = cfg.find("window"); it != cfg.end()) {
        try { window_ = std::max(1, std::stoi(it->second)); } catch (...) {}
    }
    if (auto it = cfg.find("decay"); it != cfg.end()) {
        try { decay_ = std::clamp(std::stof(it->second), 0.0f, 1.0f); } catch (...) {}
    }
    if (auto it = cfg.find("l2norm"); it != cfg.end()) {
        std::string v = it->second; std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){return (char)std::tolower(c);} );
        l2norm_ = !(v=="0"||v=="false"||v=="no"||v=="off");
    }
    if (auto it = cfg.find("passthrough_if_missing"); it != cfg.end()) {
        std::string v = it->second; std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){return (char)std::tolower(c);} );
        passthrough_if_missing_ = !(v=="0"||v=="false"||v=="no"||v=="off");
    }
}

std::string NodeReidSmooth::attr_to_id(const Attr& a) {
    if (std::holds_alternative<std::string>(a)) return std::get<std::string>(a);
    if (std::holds_alternative<int64_t>(a)) return std::to_string(std::get<int64_t>(a));
    if (std::holds_alternative<double>(a)) return std::to_string((long long)std::llround(std::get<double>(a)));
    if (std::holds_alternative<float>(a)) return std::to_string((long long)std::llround(std::get<float>(a)));
    return {};
}

void NodeReidSmooth::l2_normalize(std::vector<float>& v) {
    double ss = 0.0; for (float x : v) ss += (double)x * (double)x; ss = std::sqrt(std::max(1e-12, ss));
    if (ss <= 0) return; double inv = 1.0 / ss; for (auto& x : v) x = (float)((double)x * inv);
}

bool NodeReidSmooth::process(Packet& p, NodeContext& /*ctx*/) {
    auto it = p.tensors.find(in_key_);
    if (it == p.tensors.end()) return false;
    const auto& tv = it->second;
    if (tv.on_gpu) {
        // 当前版本仅支持 CPU 特征（避免引入 D2H 复制或 CUDA kernel），需要上游在 ORT 会话中启用 host staging
        VA_LOG_C(::va::core::LogLevel::Warn, "ms.reid") << "input on GPU; enable staged host outputs (stage_device_outputs=1) for reid.smooth";
        return false;
    }
    if (tv.dtype != va::core::DType::F32) {
        VA_LOG_C(::va::core::LogLevel::Error, "ms.reid") << "expect F32 tensor";
        return false;
    }
    // Resolve id from attrs
    auto ita = p.attrs.find(id_attr_);
    if (ita == p.attrs.end()) {
        if (passthrough_if_missing_) { p.tensors[out_key_] = tv; return true; }
        VA_LOG_C(::va::core::LogLevel::Warn, "ms.reid") << "missing id_attr='" << id_attr_ << "'";
        return false;
    }
    const std::string id = attr_to_id(ita->second);
    if (id.empty()) {
        if (passthrough_if_missing_) { p.tensors[out_key_] = tv; return true; }
        VA_LOG_C(::va::core::LogLevel::Warn, "ms.reid") << "id_attr empty after conversion";
        return false;
    }
    // Determine feature dimension: accept [D] or [1,D]
    size_t rank = tv.shape.size();
    size_t D = 0;
    if (rank == 1) D = (size_t)tv.shape[0];
    else if (rank == 2 && tv.shape[0] == 1) D = (size_t)tv.shape[1];
    else {
        VA_LOG_C(::va::core::LogLevel::Error, "ms.reid") << "unsupported shape for reid vector";
        return false;
    }
    const float* fin = static_cast<const float*>(tv.data);
    std::vector<float> cur(fin, fin + D);

    auto& st = cache_[id];
    std::vector<float> outv(D, 0.0f);
    if (method_ == Method::MEAN) {
        if (st.mean.sum.size() != D) st.mean.sum.assign(D, 0.0f);
        st.mean.window.push_back(cur);
        for (size_t i=0;i<D;++i) st.mean.sum[i] += cur[i];
        if ((int)st.mean.window.size() > window_) {
            const auto& old = st.mean.window.front();
            for (size_t i=0;i<D;++i) st.mean.sum[i] -= old[i];
            st.mean.window.pop_front();
        }
        float inv = 1.0f / (float)st.mean.window.size();
        for (size_t i=0;i<D;++i) outv[i] = st.mean.sum[i] * inv;
    } else {
        if (!st.ema.initialized || st.ema.value.size() != D) {
            st.ema.value = cur; st.ema.initialized = true;
        } else {
            const float a = decay_;
            const float b = 1.0f - a;
            for (size_t i=0;i<D;++i) st.ema.value[i] = a * st.ema.value[i] + b * cur[i];
        }
        outv = st.ema.value;
    }
    if (l2norm_) l2_normalize(outv);

    // Write out tensor (CPU view). Keep storage as member to ensure lifetime
    out_buffer_ = std::move(outv);
    va::core::TensorView out;
    out.data = out_buffer_.data();
    out.shape.clear();
    if (rank == 1) out.shape = {(int64_t)D}; else out.shape = {1, (int64_t)D};
    out.dtype = va::core::DType::F32;
    out.on_gpu = false;
    p.tensors[out_key_] = out;
    return true;
}

} } } // namespace
