#include "analyzer/postproc_yolo_det.hpp"

#include <algorithm>
#include <cmath>
#include <functional>
#include <numeric>
#include <vector>
#include <cstdint>
#include <cstring>

namespace {

static inline float default_conf_thr() { return 0.25f; }
static inline float default_nms_thr() { return 0.45f; }

float clamp(float v, float lo, float hi) {
    return std::max(lo, std::min(v, hi));
}

inline float sigmoid(float x) {
    return 1.0f / (1.0f + std::exp(-x));
}

float iou(const va::core::Box& a, const va::core::Box& b) {
    const float x1 = std::max(a.x1, b.x1);
    const float y1 = std::max(a.y1, b.y1);
    const float x2 = std::min(a.x2, b.x2);
    const float y2 = std::min(a.y2, b.y2);

    const float w = std::max(0.0f, x2 - x1);
    const float h = std::max(0.0f, y2 - y1);
    const float inter = w * h;
    const float union_area = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter;
    if (union_area <= 0.0f) {
        return 0.0f;
    }
    return inter / union_area;
}

void nonMaxSuppression(std::vector<va::core::Box>& boxes, float nms_thr) {
    if (boxes.empty()) return;
    // Precompute areas
    std::vector<float> areas(boxes.size());
    for (size_t i = 0; i < boxes.size(); ++i) {
        areas[i] = std::max(0.0f, boxes[i].x2 - boxes[i].x1) * std::max(0.0f, boxes[i].y2 - boxes[i].y1);
    }

    // Group indices by class
    std::unordered_map<int, std::vector<size_t>> by_class;
    by_class.reserve(32);
    for (size_t i = 0; i < boxes.size(); ++i) {
        by_class[boxes[i].cls].push_back(i);
    }

    std::vector<bool> suppressed(boxes.size(), false);
    std::vector<va::core::Box> result;
    result.reserve(boxes.size());

    for (auto& kv : by_class) {
        auto& idxs = kv.second;
        // Sort indices by score desc within class
        std::sort(idxs.begin(), idxs.end(), [&](size_t a, size_t b){ return boxes[a].score > boxes[b].score; });
        for (size_t ii = 0; ii < idxs.size(); ++ii) {
            size_t i = idxs[ii];
            if (suppressed[i]) continue;
            const auto& bi = boxes[i];
            result.push_back(bi);
            // suppress lower-score boxes with IoU > thr
            for (size_t jj = ii + 1; jj < idxs.size(); ++jj) {
                size_t j = idxs[jj];
                if (suppressed[j]) continue;
                const auto& bj = boxes[j];
                float x1 = std::max(bi.x1, bj.x1);
                float y1 = std::max(bi.y1, bj.y1);
                float x2 = std::min(bi.x2, bj.x2);
                float y2 = std::min(bi.y2, bj.y2);
                float w = std::max(0.0f, x2 - x1);
                float h = std::max(0.0f, y2 - y1);
                float inter = w * h;
                float uni = areas[i] + areas[j] - inter;
                float ov = uni > 0.0f ? inter / uni : 0.0f;
                if (ov > nms_thr) suppressed[j] = true;
            }
        }
    }

    boxes.swap(result);
}

} // namespace

namespace va::analyzer {

bool YoloDetectionPostprocessor::run(const std::vector<core::TensorView>& raw_outputs,
                                     const core::LetterboxMeta& meta,
                                     core::ModelOutput& output) {
    output.boxes.clear();
    output.masks.clear();

    if (raw_outputs.empty()) {
        return false;
    }

    const core::TensorView& tensor = raw_outputs.front();
    if (!tensor.data || tensor.shape.size() < 3) {
        return false;
    }

    const float* data = static_cast<const float*>(tensor.data);
    int64_t dim0 = tensor.shape[0];
    int64_t dim1 = tensor.shape[1];
    int64_t dim2 = tensor.shape[2];

    if (dim0 != 1) {
        return false;
    }

    int64_t num_det = 0;
    int64_t num_attrs = 0;
    bool channels_first = false; // indicates layout [C, N]

    // 统一处理两种常见输出形状：1x84x8400 (C,N) 与 1x8400x84 (N,C)
    if (dim1 < dim2) {
        channels_first = true;  // [C, N]
        num_det = dim2;
        num_attrs = dim1;
    } else {
        channels_first = false; // [N, C]
        num_det = dim1;
        num_attrs = dim2;
    }

    if (num_attrs < 5) {
        return false;
    }

    const int num_classes = static_cast<int>(num_attrs - 4);
    const float scale = meta.scale == 0.0f ? 1.0f : meta.scale;

    std::vector<core::Box> boxes;
    boxes.reserve(static_cast<size_t>(num_det));

    // 自适应：探测类别分数是否为 logit（需 sigmoid），以免全部被 0.25 阈值过滤
    bool need_sigmoid = false;
    {
        int64_t probe_i = 0;
        auto value_at_probe = [&](int64_t attr)->float {
            return channels_first ? data[attr * num_det + probe_i] : data[probe_i * num_attrs + attr];
        };
        float minv = 1e9f, maxv = -1e9f;
        const int probe_classes = std::min(6, num_classes);
        for (int c = 0; c < probe_classes; ++c) {
            float v = value_at_probe(4 + c);
            minv = std::min(minv, v);
            maxv = std::max(maxv, v);
        }
        // 若落在 [0,1] 外，认为是 logit，需要 sigmoid
        if (minv < -0.2f || maxv > 1.2f) need_sigmoid = true;
    }

    // CPU 路径：判定是否归一化并计算放缩系数
    bool normalized_cpu = true;
    {
        // 采样前若干值估计是否为 [0,1]
        auto v0 = [&](int64_t a)->float { return channels_first ? data[a * num_det + 0] : data[0 * num_attrs + a]; };
        float mx = 0.0f; int sample = std::min<int64_t>(num_attrs, 6);
        for (int j=0;j<sample;++j) mx = std::max(mx, std::abs(v0(j)));
        normalized_cpu = (mx <= 1.2f);
    }
    const float pre_sx_cpu = normalized_cpu ? static_cast<float>(meta.input_width)  : 1.0f;
    const float pre_sy_cpu = normalized_cpu ? static_cast<float>(meta.input_height) : 1.0f;

    const float eff_conf = (conf_thr_ > 0.0f ? conf_thr_ : default_conf_thr());
    const float eff_nms  = (nms_iou_thr_ > 0.0f ? nms_iou_thr_ : default_nms_thr());

    for (int64_t i = 0; i < num_det; ++i) {
        auto value_at = [&](int64_t attr) -> float {
            if (channels_first) {
                return data[attr * num_det + i];
            }
            return data[i * num_attrs + attr];
        };

        const float cx = value_at(0) * pre_sx_cpu;
        const float cy = value_at(1) * pre_sy_cpu;
        const float w  = value_at(2) * pre_sx_cpu;
        const float h  = value_at(3) * pre_sy_cpu;

        float best_score = 0.0f;
        int best_class = -1;
        for (int cls = 0; cls < num_classes; ++cls) {
            float cls_score = value_at(4 + cls);
            if (need_sigmoid) cls_score = sigmoid(cls_score);
            if (cls_score > best_score) {
                best_score = cls_score;
                best_class = cls;
            }
        }

        if (best_class < 0 || best_score < eff_conf) {
            continue;
        }

        const float x1 = cx - w * 0.5f;
        const float y1 = cy - h * 0.5f;
        const float x2 = cx + w * 0.5f;
        const float y2 = cy + h * 0.5f;

        const float orig_x1 = (x1 - static_cast<float>(meta.pad_x)) / scale;
        const float orig_y1 = (y1 - static_cast<float>(meta.pad_y)) / scale;
        const float orig_x2 = (x2 - static_cast<float>(meta.pad_x)) / scale;
        const float orig_y2 = (y2 - static_cast<float>(meta.pad_y)) / scale;

        const float max_w = meta.original_width > 0 ? static_cast<float>(meta.original_width) : static_cast<float>(meta.input_width);
        const float max_h = meta.original_height > 0 ? static_cast<float>(meta.original_height) : static_cast<float>(meta.input_height);

        core::Box box;
        box.x1 = clamp(orig_x1, 0.0f, std::max(0.0f, max_w - 1.0f));
        box.y1 = clamp(orig_y1, 0.0f, std::max(0.0f, max_h - 1.0f));
        box.x2 = clamp(orig_x2, 0.0f, std::max(0.0f, max_w - 1.0f));
        box.y2 = clamp(orig_y2, 0.0f, std::max(0.0f, max_h - 1.0f));
        box.score = best_score;
        box.cls = best_class;

        if (box.x2 > box.x1 && box.y2 > box.y1) {
            boxes.emplace_back(box);
        }
    }

    if (boxes.empty()) {
        return true;
    }

    nonMaxSuppression(boxes, eff_nms);
    output.boxes = std::move(boxes);
    return true;
}

} // namespace va::analyzer

#ifdef USE_CUDA
#include "analyzer/postproc_yolo_det.hpp"
#include "analyzer/logging_util.hpp"

#if defined(__has_include)
#  if __has_include(<cuda_runtime.h>)
#    include <cuda_runtime.h>
#    define VA_HAS_CUDA_RUNTIME 1
#  else
#    define VA_HAS_CUDA_RUNTIME 0
#  endif
#else
#  include <cuda_runtime.h>
#  define VA_HAS_CUDA_RUNTIME 1
#endif

// CUDA decode kernels（支持 pre_sx/pre_sy 与 FP16 输入）
#include "analyzer/cuda/yolo_decode_kernels.hpp"
#include "analyzer/cuda/postproc_yolo_nms_kernels.hpp"

namespace va::analyzer {

bool YoloDetectionPostprocessorCUDA::run(const std::vector<core::TensorView>& raw_outputs,
                                         const core::LetterboxMeta& meta,
                                         core::ModelOutput& output) {
    // If no outputs or not a tensor-like shape, fallback
    if (raw_outputs.empty()) {
        return false;
    }
    const core::TensorView& t = raw_outputs.front();
    if (t.shape.size() < 3) {
        YoloDetectionPostprocessor cpu;
        return cpu.run(raw_outputs, meta, output);
    }

    // If already on CPU, reuse CPU implementation
    if (!t.on_gpu) {
        YoloDetectionPostprocessor cpu;
        return cpu.run(raw_outputs, meta, output);
    }

#if VA_HAS_CUDA_RUNTIME
    // 设备侧解码快路径（遵循“检测框问题修复.md”）
    {
        int64_t dim0 = t.shape[0];
        int64_t dim1 = t.shape[1];
        int64_t dim2 = t.shape[2];
        if (dim0 == 1) {
            bool channels_first = false;
            int num_det=0, num_attrs=0;
            if (dim1 < dim2) { channels_first = true; num_det = static_cast<int>(dim2); num_attrs = static_cast<int>(dim1); }
            else { channels_first = false; num_det = static_cast<int>(dim1); num_attrs = static_cast<int>(dim2); }
            if (num_attrs >= 5) {
                const int num_classes = static_cast<int>(num_attrs - 4);
                // 规范化预缩放（与 CPU 路径保持一致）
                bool normalized = true;
                if (t.dtype == core::DType::F32) {
                    int sample = std::min(num_attrs, 6);
                    float mx = 0.0f;
                    for (int a = 0; a < sample; ++a) {
                        size_t idx = channels_first ? (size_t)a * (size_t)num_det : (size_t)a;
                        float v = 0.0f;
                        cudaMemcpy(&v, static_cast<const float*>(t.data) + idx, sizeof(float), cudaMemcpyDeviceToHost);
                        mx = std::max(mx, std::abs(v));
                    }
                    normalized = (mx <= 1.2f);
                }
                // 判定是否需要对类别分数做 sigmoid（与 CPU 路径保持一致）
                bool need_sigmoid = true;
                if (num_classes > 0) {
                    float minv = 1e9f, maxv = -1e9f;
                    int probe = std::min(num_classes, 6);
                    if (t.dtype == core::DType::F32) {
                        for (int c = 0; c < probe; ++c) {
                            int attr = 4 + c;
                            size_t idx = channels_first ? (size_t)attr * (size_t)num_det : (size_t)attr;
                            float v = 0.0f;
                            cudaMemcpy(&v, static_cast<const float*>(t.data) + idx, sizeof(float), cudaMemcpyDeviceToHost);
                            minv = std::min(minv, v);
                            maxv = std::max(maxv, v);
                        }
                    } else if (t.dtype == core::DType::F16) {
                        auto h2f = [](uint16_t h)->float {
                            uint32_t s = (h & 0x8000u) << 16;
                            uint32_t e = (h & 0x7C00u) >> 10;
                            uint32_t f = (h & 0x03FFu);
                            uint32_t out_e, out_f;
                            if (e == 0) {
                                if (f == 0) { out_e = 0; out_f = 0; }
                                else {
                                    e = 1; while ((f & 0x0400u) == 0) { f <<= 1; e--; }
                                    f &= 0x03FFu;
                                    out_e = e + (127 - 15);
                                    out_f = f << 13;
                                }
                            } else if (e == 31) { // Inf/NaN
                                out_e = 255; out_f = f ? (f << 13) : 0;
                            } else {
                                out_e = e + (127 - 15);
                                out_f = f << 13;
                            }
                            uint32_t out = s | (out_e << 23) | out_f;
                            float r;
                            std::memcpy(&r, &out, sizeof(float));
                            return r;
                        };
                        const uint16_t* dhalf = reinterpret_cast<const uint16_t*>(t.data);
                        for (int c = 0; c < probe; ++c) {
                            int attr = 4 + c;
                            size_t idx = channels_first ? (size_t)attr * (size_t)num_det : (size_t)attr;
                            uint16_t hv = 0;
                            cudaMemcpy(&hv, dhalf + idx, sizeof(uint16_t), cudaMemcpyDeviceToHost);
                            float v = h2f(hv);
                            minv = std::min(minv, v);
                            maxv = std::max(maxv, v);
                        }
                    }
                    if (minv >= -0.2f && maxv <= 1.2f) {
                        need_sigmoid = false;
                    }
                }
                const float pre_sx = normalized ? static_cast<float>(meta.input_width)  : 1.0f;
                const float pre_sy = normalized ? static_cast<float>(meta.input_height) : 1.0f;
                const float eff_conf = (conf_thr_ > 0.0f ? conf_thr_ : default_conf_thr());
                const float eff_nms  = (nms_iou_thr_ > 0.0f ? nms_iou_thr_ : default_nms_thr());

                float *d_boxes=nullptr, *d_scores=nullptr; int32_t* d_classes=nullptr; int *d_count=nullptr;
                cudaStream_t st = reinterpret_cast<cudaStream_t>(stream_);
                // 精度策略：若 prefer_fp16_ 且张量为 F16，则直接在 F16 上 decode；
                // 否则统一在 GPU 上转换为 float32 再 decode。
                float* d_logits_f32 = nullptr;
                const float* decode_src = nullptr;
                const bool use_fp16_path = prefer_fp16_ && (t.dtype == core::DType::F16);
                size_t elem_count = static_cast<size_t>(num_det) * static_cast<size_t>(num_attrs);
                if (!use_fp16_path) {
                    if (t.dtype == core::DType::F16) {
                        if (cudaMalloc(&d_logits_f32, elem_count * sizeof(float)) != cudaSuccess) {
                            goto DECODE_CLEANUP_EARLY;
                        }
#if VA_HAS_CUDA_RUNTIME
                        if (va::analyzer::cudaops::half_to_float(
                                reinterpret_cast<const __half*>(t.data),
                                d_logits_f32,
                                static_cast<int>(elem_count),
                                st) != cudaSuccess) {
                            goto DECODE_CLEANUP_EARLY;
                        }
#endif
                        decode_src = d_logits_f32;
                    } else {
                        decode_src = static_cast<const float*>(t.data);
                    }
                }

                if (cudaMalloc(&d_boxes,  num_det * 4 * sizeof(float))==cudaSuccess &&
                    cudaMalloc(&d_scores, num_det * sizeof(float))==cudaSuccess &&
                    cudaMalloc(&d_classes,num_det * sizeof(int32_t))==cudaSuccess &&
                    cudaMalloc(&d_count, sizeof(int))==cudaSuccess) {
                    cudaMemsetAsync(d_count, 0, sizeof(int), st);
                    const float conf_thr = eff_conf;
                    const float scale = meta.scale;
                    const int pad_x = meta.pad_x, pad_y = meta.pad_y;
                    const int ow = (meta.original_width>0?meta.original_width:meta.input_width);
                    const int oh = (meta.original_height>0?meta.original_height:meta.input_height);
                    cudaError_t kerr = cudaSuccess;
                    // 预解码诊断
                    {
                        auto lvl = va::analyzer::logutil::log_level_for_tag("ms.nms");
                        auto thr = va::analyzer::logutil::log_throttle_ms_for_tag("ms.nms", 3000);
                        VA_LOG_THROTTLED(lvl, "ms.nms", thr)
                            << "gpu_decode.pre ch_first=" << (channels_first?1:0)
                            << " num_det=" << num_det << " num_attrs=" << num_attrs
                            << " dtype=" << (t.dtype==core::DType::F16?"F16":"F32")
                            << " normalized=" << std::boolalpha << normalized
                            << " pre_sx=" << pre_sx << " pre_sy=" << pre_sy
                            << " thr=" << conf_thr
                            << " need_sigmoid=" << need_sigmoid;
                    }
                    if (use_fp16_path) {
                        kerr = va::analyzer::cudaops::yolo_decode_to_yxyx_fp16(
                            reinterpret_cast<const __half*>(t.data), num_det, num_attrs, num_attrs-4,
                            channels_first?1:0, conf_thr, need_sigmoid?1:0,
                            pre_sx, pre_sy, scale, pad_x, pad_y, ow, oh,
                            d_boxes, d_scores, d_classes, d_count, st);
                    } else {
                        kerr = va::analyzer::cudaops::yolo_decode_to_yxyx(
                            decode_src, num_det, num_attrs, num_attrs-4,
                            channels_first?1:0, conf_thr, need_sigmoid?1:0,
                            pre_sx, pre_sy, scale, pad_x, pad_y, ow, oh,
                            d_boxes, d_scores, d_classes, d_count, st);
                    }
                    if (kerr == cudaSuccess) {
                        int h_count=0; cudaMemcpyAsync(&h_count, d_count, sizeof(int), cudaMemcpyDeviceToHost, st); cudaStreamSynchronize(st);
                        h_count = std::max(0, std::min(h_count, num_det));
                        {
                            auto lvl2 = va::analyzer::logutil::log_level_for_tag("ms.nms");
                            auto thr2 = va::analyzer::logutil::log_throttle_ms_for_tag("ms.nms", 3000);
                            VA_LOG_THROTTLED(lvl2, "ms.nms", thr2)
                                << "gpu_decode candidates=" << h_count
                                << " normalized=" << std::boolalpha << normalized
                                << " pre_sx=" << pre_sx << " pre_sy=" << pre_sy
                                << " thr=" << conf_thr
                                << " dtype=" << (t.dtype==core::DType::F16?(use_fp16_path?"F16":"F16->F32"):"F32")
                                << " ch_first=" << (channels_first?1:0)
                                << " num_det=" << num_det << " num_attrs=" << num_attrs;
                        }
                        bool gpu_ok = false;
                        if (h_count > 0) {
                            int *d_keep=nullptr, *d_kept=nullptr;
                            if (cudaMalloc(&d_keep, h_count*sizeof(int))==cudaSuccess &&
                                cudaMalloc(&d_kept, sizeof(int))==cudaSuccess &&
                                cudaMemsetAsync(d_kept, 0, sizeof(int), st)==cudaSuccess) {
                                if (va::analyzer::cudaops::nms_yxyx_per_class(
                                        d_boxes, d_scores, d_classes, h_count, eff_nms,
                                        d_keep, d_kept, st) == cudaSuccess) {
                                    std::vector<float> h_boxes(h_count*4), h_scores(h_count);
                                    std::vector<int32_t> h_classes(h_count);
                                    std::vector<int> h_keep(h_count);
                                    if (cudaMemcpy(h_boxes.data(), d_boxes, h_boxes.size()*sizeof(float), cudaMemcpyDeviceToHost)==cudaSuccess &&
                                        cudaMemcpy(h_scores.data(), d_scores, h_scores.size()*sizeof(float), cudaMemcpyDeviceToHost)==cudaSuccess &&
                                        cudaMemcpy(h_classes.data(), d_classes, h_classes.size()*sizeof(int32_t), cudaMemcpyDeviceToHost)==cudaSuccess &&
                                        cudaMemcpy(h_keep.data(), d_keep, h_count*sizeof(int), cudaMemcpyDeviceToHost)==cudaSuccess) {
                                        output.boxes.clear(); output.masks.clear();
                                        for (int i=0;i<h_count;++i) if (h_keep[i]) {
                                            core::Box b; b.x1=h_boxes[i*4+0]; b.y1=h_boxes[i*4+1]; b.x2=h_boxes[i*4+2]; b.y2=h_boxes[i*4+3];
                                            b.score=h_scores[i]; b.cls=h_classes[i]; output.boxes.emplace_back(b);
                                        }
                                        gpu_ok = !output.boxes.empty();
                                    }
                                }
                            }
                            if (d_kept) cudaFree(d_kept); if (d_keep) cudaFree(d_keep);
                        }
                        if (!gpu_ok) {
                            std::vector<float> h_boxes(h_count*4), h_scores(h_count); std::vector<int32_t> h_classes(h_count);
                            if (h_count>0) {
                                cudaMemcpy(h_boxes.data(), d_boxes, h_boxes.size()*sizeof(float), cudaMemcpyDeviceToHost);
                                cudaMemcpy(h_scores.data(), d_scores, h_scores.size()*sizeof(float), cudaMemcpyDeviceToHost);
                                cudaMemcpy(h_classes.data(), d_classes, h_classes.size()*sizeof(int32_t), cudaMemcpyDeviceToHost);
                            }
                            std::vector<core::Box> boxes; boxes.reserve(static_cast<size_t>(h_count));
                            for (int i=0;i<h_count;++i){ core::Box b; b.x1=h_boxes[i*4+0]; b.y1=h_boxes[i*4+1]; b.x2=h_boxes[i*4+2]; b.y2=h_boxes[i*4+3]; b.score=h_scores[i]; b.cls=h_classes[i]; boxes.emplace_back(b);}    
                            if (!boxes.empty()) { nonMaxSuppression(boxes, eff_nms); }
                            output.boxes = std::move(boxes); output.masks.clear();
                        }
                        // 释放并返回
                        if (d_boxes) cudaFree(d_boxes); if (d_scores) cudaFree(d_scores);
                        if (d_classes) cudaFree(d_classes); if (d_count) cudaFree(d_count);
                        if (d_logits_f32) cudaFree(d_logits_f32);
                        return true;
                    } else {
                        VA_LOG_C(::va::core::LogLevel::Warn, "ms.nms") << "gpu_decode kernel error code=" << int(kerr);
                    }
                }
DECODE_CLEANUP_EARLY:
                if (d_boxes) cudaFree(d_boxes); if (d_scores) cudaFree(d_scores);
                if (d_classes) cudaFree(d_classes); if (d_count) cudaFree(d_count);
                if (d_logits_f32) cudaFree(d_logits_f32);
            }
        }
    }
#endif
#if 0 // legacy host-decode path disabled per 检测框问题修复.md
    // Decode YOLO tensor on host (D2H) to boxes/scores/classes; then run CUDA NMS if kernels available, else CPU NMS
    size_t count = 1;
    for (auto d : t.shape) { count *= static_cast<size_t>(d > 0 ? d : 1); }
    if (count == 0) return false;
    std::vector<float> host(count);
    if (cudaMemcpy(host.data(), t.data, count * sizeof(float), cudaMemcpyDeviceToHost) != cudaSuccess) {
        return false;
    }

    // Interpret layout like CPU path
    int64_t dim0 = t.shape[0];
    int64_t dim1 = t.shape[1];
    int64_t dim2 = t.shape[2];
    bool channels_first = false;
    int64_t num_det, num_attrs;
    if (dim1 < dim2) { channels_first = true; num_det = dim2; num_attrs = dim1; }
    else { channels_first = false; num_det = dim1; num_attrs = dim2; }
    if (dim0 != 1 || num_attrs < 5) return false;
    const int num_classes = static_cast<int>(num_attrs - 4);

    auto value_at = [&](int64_t i, int64_t a)->float {
        return channels_first ? host[a * num_det + i] : host[i * num_attrs + a];
    };

    // 自适应：判定是否需要对类别分数做 sigmoid
    bool need_sigmoid = false;
    {
        float minv = 1e9f, maxv = -1e9f;
        const int probe = std::min(6, num_classes);
        for (int c=0;c<probe;++c){ float v = value_at(0, 4+c); minv = std::min(minv, v); maxv = std::max(maxv, v); }
        if (minv < -0.2f || maxv > 1.2f) need_sigmoid = true;
    }

    struct Cand { float x1,y1,x2,y2,score; int cls; };
    std::vector<Cand> cands;
    cands.reserve(static_cast<size_t>(num_det));
    for (int64_t i = 0; i < num_det; ++i) {
        float cx = value_at(i,0), cy = value_at(i,1), w = value_at(i,2), h = value_at(i,3);
        // best class score
        float best=0.0f; int best_c=-1;
        for (int c=0;c<num_classes;++c){ float s=value_at(i,4+c); if (need_sigmoid) s = 1.0f/(1.0f+std::exp(-s)); if (s>best){ best=s; best_c=c; }}
        if (best_c<0 || best<getScoreThreshold()) continue; // score threshold aligned with CPU path
        float x1 = cx - 0.5f*w, y1 = cy - 0.5f*h, x2 = cx + 0.5f*w, y2 = cy + 0.5f*h;
        float ox1 = (x1 - static_cast<float>(meta.pad_x)) / (meta.scale==0.0f?1.0f:meta.scale);
        float oy1 = (y1 - static_cast<float>(meta.pad_y)) / (meta.scale==0.0f?1.0f:meta.scale);
        float ox2 = (x2 - static_cast<float>(meta.pad_x)) / (meta.scale==0.0f?1.0f:meta.scale);
        float oy2 = (y2 - static_cast<float>(meta.pad_y)) / (meta.scale==0.0f?1.0f:meta.scale);
        float mw = static_cast<float>(meta.original_width>0?meta.original_width:meta.input_width) - 1.0f;
        float mh = static_cast<float>(meta.original_height>0?meta.original_height:meta.input_height) - 1.0f;
        Cand cd;
        cd.x1 = std::max(0.0f, std::min(ox1, mw));
        cd.y1 = std::max(0.0f, std::min(oy1, mh));
        cd.x2 = std::max(0.0f, std::min(ox2, mw));
        cd.y2 = std::max(0.0f, std::min(oy2, mh));
        cd.score = best; cd.cls = best_c;
        if (cd.x2>cd.x1 && cd.y2>cd.y1) cands.emplace_back(cd);
    }

    if (cands.empty()) { output.boxes.clear(); output.masks.clear(); return true; }

    // Sort by score desc on host (required by our simple GPU kernel)
    std::sort(cands.begin(), cands.end(), [](const Cand& a, const Cand& b){ return a.score > b.score; });

#if defined(VA_HAS_CUDA_KERNELS)
    // Move boxes/classes to device, run CUDA NMS
    const int N = static_cast<int>(cands.size());
    std::vector<float> h_boxes(N*4);
    std::vector<float> h_scores(N);
    std::vector<int32_t> h_classes(N);
    for (int i=0;i<N;++i){ h_boxes[i*4+0]=cands[i].x1; h_boxes[i*4+1]=cands[i].y1; h_boxes[i*4+2]=cands[i].x2; h_boxes[i*4+3]=cands[i].y2; h_scores[i]=cands[i].score; h_classes[i]=cands[i].cls; }
    float *d_boxes=nullptr,*d_scores=nullptr; int32_t* d_classes=nullptr; int *d_keep=nullptr, *d_kept=nullptr;
    if (cudaMalloc(&d_boxes, h_boxes.size()*sizeof(float))!=cudaSuccess) goto CPU_NMS;
    if (cudaMalloc(&d_scores, h_scores.size()*sizeof(float))!=cudaSuccess) goto CLEAN1;
    if (cudaMalloc(&d_classes, h_classes.size()*sizeof(int32_t))!=cudaSuccess) goto CLEAN2;
    if (cudaMalloc(&d_keep, N*sizeof(int))!=cudaSuccess) goto CLEAN3;
    if (cudaMalloc(&d_kept, sizeof(int))!=cudaSuccess) goto CLEAN4;
    if (cudaMemcpy(d_boxes, h_boxes.data(), h_boxes.size()*sizeof(float), cudaMemcpyHostToDevice)!=cudaSuccess) goto CLEAN5;
    if (cudaMemcpy(d_scores, h_scores.data(), h_scores.size()*sizeof(float), cudaMemcpyHostToDevice)!=cudaSuccess) goto CLEAN5;
    if (cudaMemcpy(d_classes, h_classes.data(), h_classes.size()*sizeof(int32_t), cudaMemcpyHostToDevice)!=cudaSuccess) goto CLEAN5;
    if (cudaMemset(d_kept, 0, sizeof(int))!=cudaSuccess) goto CLEAN5;
    if (va::analyzer::cudaops::nms_yxyx_per_class(d_boxes, d_scores, d_classes, N, eff_nms, d_keep, d_kept, nullptr)!=cudaSuccess) goto CLEAN5;
    {
        std::vector<int> h_keep(N);
        if (cudaMemcpy(h_keep.data(), d_keep, N*sizeof(int), cudaMemcpyDeviceToHost)!=cudaSuccess) goto CLEAN5;
        output.boxes.clear(); output.masks.clear();
        for (int i=0;i<N;++i){ if (h_keep[i]) { core::Box b; b.x1=cands[i].x1; b.y1=cands[i].y1; b.x2=cands[i].x2; b.y2=cands[i].y2; b.score=cands[i].score; b.cls=cands[i].cls; output.boxes.emplace_back(b);} }
    }
    // cleanup
    CLEAN5: if (d_kept) cudaFree(d_kept);
    CLEAN4: if (d_keep) cudaFree(d_keep);
    CLEAN3: if (d_classes) cudaFree(d_classes);
    CLEAN2: if (d_scores) cudaFree(d_scores);
    CLEAN1: if (d_boxes) cudaFree(d_boxes);
    if (!output.boxes.empty()) return true;
#endif

CPU_NMS:
    // Fallback: CPU NMS identical浜庣幇鏈夊疄鐜?    {
        // 绠€鍗?NMS锛氭寜 CPU 瀹炵幇閫昏緫
        auto iou = [](const Cand& a, const Cand& b){
            float x1 = std::max(a.x1,b.x1), y1=std::max(a.y1,b.y1), x2=std::min(a.x2,b.x2), y2=std::min(a.y2,b.y2);
            float w=std::max(0.0f,x2-x1), h=std::max(0.0f,y2-y1); float inter=w*h;
            float ua=(a.x2-a.x1)*(a.y2-a.y1) + (b.x2-b.x1)*(b.y2-b.y1) - inter; return ua>0.0f? inter/ua : 0.0f;
        };
        std::vector<bool> sup(cands.size(), false);
        output.boxes.clear(); output.masks.clear();
        for (size_t i=0;i<cands.size();++i){ if (sup[i]) continue; const auto& ci=cands[i]; output.boxes.push_back({ci.x1,ci.y1,ci.x2,ci.y2,ci.score,ci.cls}); for (size_t j=i+1;j<cands.size();++j){ if (sup[j]) continue; if (cands[j].cls!=ci.cls) continue; if (iou(ci,cands[j])>eff_nms) sup[j]=true; } }
        return true;
    }
#else
    return false;
#endif
}

} // namespace va::analyzer
#endif


