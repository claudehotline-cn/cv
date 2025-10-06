#include "analyzer/postproc_yolo_det.hpp"

#include <algorithm>
#include <cmath>
#include <functional>
#include <numeric>
#include <vector>

namespace {

constexpr float kNMSThreshold = 0.45f;

inline float getScoreThreshold() {
    float thr = 0.25f;
    if (const char* e = std::getenv("VA_CONF_THRESH")) {
        try { thr = std::stof(e); } catch (...) {}
    } else if (const char* e2 = std::getenv("VA_SCORE_THR")) {
        try { thr = std::stof(e2); } catch (...) {}
    }
    if (thr < 0.0f) thr = 0.0f; if (thr > 1.0f) thr = 1.0f;
    return thr;
}

float clamp(float v, float lo, float hi) {
    return std::max(lo, std::min(v, hi));
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

void nonMaxSuppression(std::vector<va::core::Box>& boxes) {
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
                if (ov > kNMSThreshold) suppressed[j] = true;
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

    if (dim1 <= dim2) {
        num_det = dim1;
        num_attrs = dim2;
    } else {
        num_det = dim2;
        num_attrs = dim1;
        channels_first = true;
    }

    if (num_attrs < 5) {
        return false;
    }

    const int num_classes = static_cast<int>(num_attrs - 4);
    const float scale = meta.scale == 0.0f ? 1.0f : meta.scale;

    std::vector<core::Box> boxes;
    boxes.reserve(static_cast<size_t>(num_det));

    for (int64_t i = 0; i < num_det; ++i) {
        auto value_at = [&](int64_t attr) -> float {
            if (channels_first) {
                return data[attr * num_det + i];
            }
            return data[i * num_attrs + attr];
        };

        const float cx = value_at(0);
        const float cy = value_at(1);
        const float w = value_at(2);
        const float h = value_at(3);

        float best_score = 0.0f;
        int best_class = -1;
        for (int cls = 0; cls < num_classes; ++cls) {
            const float cls_score = value_at(4 + cls);
            if (cls_score > best_score) {
                best_score = cls_score;
                best_class = cls;
            }
        }

        const float score_thr = getScoreThreshold();
        if (best_class < 0 || best_score < score_thr) {
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

    nonMaxSuppression(boxes);
    output.boxes = std::move(boxes);
    return true;
}

} // namespace va::analyzer

#if defined(USE_CUDA) && !defined(UNIT_TEST_NO_CUDA)
#include "analyzer/postproc_yolo_det.hpp"

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
#if VA_HAS_CUDA_RUNTIME && defined(VA_HAS_CUDA_KERNELS)
    // Fast path: device-side decode + CUDA NMS, then compact to host
    {
        int64_t dim0 = t.shape[0];
        int64_t dim1 = t.shape[1];
        int64_t dim2 = t.shape[2];
        if (dim0 == 1) {
            bool channels_first = false;
            int num_det = 0, num_attrs = 0;
            if (dim1 <= dim2) { num_det = static_cast<int>(dim1); num_attrs = static_cast<int>(dim2); }
            else { num_det = static_cast<int>(dim2); num_attrs = static_cast<int>(dim1); channels_first = true; }
            if (num_attrs >= 5 && num_det > 0) {
                float *d_boxes=nullptr, *d_scores=nullptr; int32_t* d_classes=nullptr; int* d_count=nullptr; int* d_keep=nullptr;
                if (cudaMalloc(&d_boxes, static_cast<size_t>(num_det)*4*sizeof(float)) == cudaSuccess &&
                    cudaMalloc(&d_scores, static_cast<size_t>(num_det)*sizeof(float)) == cudaSuccess &&
                    cudaMalloc(&d_classes, static_cast<size_t>(num_det)*sizeof(int32_t)) == cudaSuccess &&
                    cudaMalloc(&d_count, sizeof(int)) == cudaSuccess &&
                    cudaMemset(d_count, 0, sizeof(int)) == cudaSuccess) {
                    float scale = meta.scale == 0.0f ? 1.0f : meta.scale;
                    int orig_w = meta.original_width > 0 ? meta.original_width : meta.input_width;
                    int orig_h = meta.original_height > 0 ? meta.original_height : meta.input_height;
                    if (va::analyzer::cudaops::yolo_decode_to_yxyx(static_cast<const float*>(t.data),
                        num_det, num_attrs, num_attrs - 4, channels_first ? 1 : 0,
                        getScoreThreshold(), scale, meta.pad_x, meta.pad_y, orig_w, orig_h,
                        d_boxes, d_scores, d_classes, d_count, nullptr) == cudaSuccess &&
                        cudaMalloc(&d_keep, static_cast<size_t>(num_det)*sizeof(int)) == cudaSuccess &&
                        va::analyzer::cudaops::nms_yxyx_per_class(d_boxes, d_scores, d_classes, num_det, 0.45f, d_keep, nullptr, nullptr) == cudaSuccess) {
                        int h_count = 0;
                        std::vector<int> h_keep(num_det, 0);
                        std::vector<float> h_boxes(static_cast<size_t>(num_det)*4);
                        std::vector<float> h_scores(static_cast<size_t>(num_det));
                        std::vector<int32_t> h_classes(static_cast<size_t>(num_det));
                        if (cudaMemcpy(&h_count, d_count, sizeof(int), cudaMemcpyDeviceToHost) == cudaSuccess &&
                            cudaMemcpy(h_keep.data(), d_keep, static_cast<size_t>(num_det)*sizeof(int), cudaMemcpyDeviceToHost) == cudaSuccess &&
                            cudaMemcpy(h_boxes.data(), d_boxes, h_boxes.size()*sizeof(float), cudaMemcpyDeviceToHost) == cudaSuccess &&
                            cudaMemcpy(h_scores.data(), d_scores, h_scores.size()*sizeof(float), cudaMemcpyDeviceToHost) == cudaSuccess &&
                            cudaMemcpy(h_classes.data(), d_classes, h_classes.size()*sizeof(int32_t), cudaMemcpyDeviceToHost) == cudaSuccess) {
                            output.boxes.clear(); output.masks.clear();
                            h_count = std::min(h_count, num_det);
                            for (int i=0;i<num_det;++i) {
                                if (!h_keep[i]) continue;
                                core::Box b; b.x1=h_boxes[i*4+0]; b.y1=h_boxes[i*4+1]; b.x2=h_boxes[i*4+2]; b.y2=h_boxes[i*4+3];
                                b.score=h_scores[i]; b.cls=static_cast<int>(h_classes[i]);
                                output.boxes.emplace_back(b);
                            }
                            if (d_keep) cudaFree(d_keep);
                            if (d_count) cudaFree(d_count);
                            if (d_classes) cudaFree(d_classes);
                            if (d_scores) cudaFree(d_scores);
                            if (d_boxes) cudaFree(d_boxes);
                            return true;
                        }
                    }
                }
                if (d_keep) cudaFree(d_keep);
                if (d_count) cudaFree(d_count);
                if (d_classes) cudaFree(d_classes);
                if (d_scores) cudaFree(d_scores);
                if (d_boxes) cudaFree(d_boxes);
            }
        }
    }
#endif

#if VA_HAS_CUDA_RUNTIME
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
    if (dim1 <= dim2) { num_det = dim1; num_attrs = dim2; }
    else { num_det = dim2; num_attrs = dim1; channels_first = true; }
    if (dim0 != 1 || num_attrs < 5) return false;
    const int num_classes = static_cast<int>(num_attrs - 4);

    auto value_at = [&](int64_t i, int64_t a)->float {
        return channels_first ? host[a * num_det + i] : host[i * num_attrs + a];
    };

    struct Cand { float x1,y1,x2,y2,score; int cls; };
    std::vector<Cand> cands;
    cands.reserve(static_cast<size_t>(num_det));
    const float score_thr2 = getScoreThreshold();
    for (int64_t i = 0; i < num_det; ++i) {
        float cx = value_at(i,0), cy = value_at(i,1), w = value_at(i,2), h = value_at(i,3);
        // best class score
        float best=0.0f; int best_c=-1;
        for (int c=0;c<num_classes;++c){ float s=value_at(i,4+c); if (s>best){ best=s; best_c=c; }}
        if (best_c<0 || best<score_thr2) continue; // score threshold (env overridable)
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
    if (va::analyzer::cudaops::nms_yxyx_per_class(d_boxes, d_scores, d_classes, N, 0.45f, d_keep, d_kept, nullptr)!=cudaSuccess) goto CLEAN5;
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
    // Fallback: CPU NMS identical于现有实现
    {
        // 简单 NMS：按 CPU 实现逻辑
        auto iou = [](const Cand& a, const Cand& b){
            float x1 = std::max(a.x1,b.x1), y1=std::max(a.y1,b.y1), x2=std::min(a.x2,b.x2), y2=std::min(a.y2,b.y2);
            float w=std::max(0.0f,x2-x1), h=std::max(0.0f,y2-y1); float inter=w*h;
            float ua=(a.x2-a.x1)*(a.y2-a.y1) + (b.x2-b.x1)*(b.y2-b.y1) - inter; return ua>0.0f? inter/ua : 0.0f;
        };
        std::vector<bool> sup(cands.size(), false);
        output.boxes.clear(); output.masks.clear();
        for (size_t i=0;i<cands.size();++i){ if (sup[i]) continue; const auto& ci=cands[i]; output.boxes.push_back({ci.x1,ci.y1,ci.x2,ci.y2,ci.score,ci.cls}); for (size_t j=i+1;j<cands.size();++j){ if (sup[j]) continue; if (cands[j].cls!=ci.cls) continue; if (iou(ci,cands[j])>0.45f) sup[j]=true; } }
        return true;
    }
#else
    return false;
#endif
}

} // namespace va::analyzer
#endif
#ifdef USE_CUDA
#include "analyzer/cuda/postproc_yolo_nms_kernels.hpp"
#include "analyzer/cuda/yolo_decode_kernels.hpp"
#endif
