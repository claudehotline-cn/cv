#include "analyzer/multistage/node_join.hpp"
#include "analyzer/multistage/nodes_common.hpp"
#include "core/logger.hpp"
#include <cstring>
#ifdef USE_CUDA
#  if defined(__has_include)
#    if __has_include(<cuda_runtime.h>)
#      include <cuda_runtime.h>
#      define VA_MS_JOIN_HAS_CUDA 1
#    else
#      define VA_MS_JOIN_HAS_CUDA 0
#    endif
#  else
#    include <cuda_runtime.h>
#    define VA_MS_JOIN_HAS_CUDA 1
#  endif
#else
#  define VA_MS_JOIN_HAS_CUDA 0
#endif

using va::analyzer::multistage::util::split_csv;
using va::analyzer::multistage::util::get_or_int;

namespace va { namespace analyzer { namespace multistage {

NodeJoin::NodeJoin(const std::unordered_map<std::string,std::string>& cfg) {
    if (auto it = cfg.find("ins"); it != cfg.end()) ins_ = split_csv(it->second);
    if (auto it = cfg.find("out"); it != cfg.end()) out_key_ = it->second;
    axis_ = get_or_int(cfg, "axis", 1);
    prefer_gpu_ = get_or_int(cfg, "prefer_gpu", 1) != 0;
}

static inline size_t product_except(const std::vector<int64_t>& dims, int start, int end) {
    size_t v=1; for (int i=start;i<end;++i) v *= (size_t)(dims[i]>0?dims[i]:1); return v; }

bool NodeJoin::process(Packet& p, NodeContext& ctx) {
    if (ins_.empty()) return true;
    std::vector<const va::core::TensorView*> tvs;
    tvs.reserve(ins_.size());
    for (auto& k : ins_) {
        auto it = p.tensors.find(k);
        if (it == p.tensors.end()) {
            VA_LOG_C(::va::core::LogLevel::Error, "ms.join") << "missing input tensor: " << k;
            return false;
        }
        tvs.push_back(&it->second);
    }
    // Determine shape compatibility
    const auto& base = *tvs.front();
    const int rank = (int)base.shape.size();
    int axis = axis_ < 0 ? axis_ + rank : axis_;
    if (axis < 0 || axis >= rank) { VA_LOG_C(::va::core::LogLevel::Error, "ms.join") << "axis out of range"; return false; }
    std::vector<int64_t> out_shape = base.shape;
    size_t out_axis = (size_t)out_shape[axis];
    bool all_gpu = base.on_gpu;
    for (size_t i=1;i<tvs.size();++i) {
        const auto& t = *tvs[i];
        if ((int)t.shape.size() != rank) { VA_LOG_C(::va::core::LogLevel::Error, "ms.join") << "rank mismatch"; return false; }
        for (int d=0; d<rank; ++d) {
            if (d == axis) continue;
            if (t.shape[d] != out_shape[d]) { VA_LOG_C(::va::core::LogLevel::Error, "ms.join") << "shape mismatch on dim=" << d; return false; }
        }
        out_axis += (size_t)t.shape[axis];
        all_gpu = all_gpu && t.on_gpu;
    }
    out_shape[axis] = (int64_t)out_axis;

    const size_t total_elems = product_except(out_shape, 0, rank);
    (void)total_elems;
    const size_t elt_stride = sizeof(float);
    const size_t block_after = product_except(base.shape, axis+1, rank);
    const size_t block_before = product_except(base.shape, 0, axis);
    // Compute per-input axis size and cumulative offsets
    std::vector<size_t> axis_sizes(tvs.size());
    std::vector<size_t> axis_offsets(tvs.size());
    size_t cum = 0;
    for (size_t i=0;i<tvs.size();++i) {
        axis_sizes[i] = (size_t)tvs[i]->shape[axis];
        axis_offsets[i] = cum; cum += axis_sizes[i];
    }

    const bool use_gpu = prefer_gpu_ && all_gpu && ctx.gpu_pool;
    if (use_gpu) {
#if VA_MS_JOIN_HAS_CUDA
        // Allocate precisely by bytes
        size_t out_bytes = 1; for (auto d: out_shape) out_bytes *= (size_t)(d>0?d:1); out_bytes *= elt_stride;
        va::core::GpuBufferPool::Memory mem = ctx.gpu_pool->acquire(out_bytes);
        if (!mem.ptr) { VA_LOG_C(::va::core::LogLevel::Error, "ms.join") << "gpu_pool acquire failed"; return false; }
        uint8_t* d_out = static_cast<uint8_t*>(mem.ptr);
        
        // Optional stream-aware copies
        cudaStream_t stream = nullptr;
        if (ctx.stream) {
            stream = reinterpret_cast<cudaStream_t>(ctx.stream);
        }
        for (size_t outer = 0; outer < block_before; ++outer) {
            for (size_t i=0;i<tvs.size();++i) {
                size_t copy_elems = axis_sizes[i] * block_after;
                size_t in_offset_elems = outer * axis_sizes[i] * block_after;
                size_t out_offset_elems = outer * out_axis * block_after + axis_offsets[i] * block_after;
                const uint8_t* d_src = static_cast<const uint8_t*>(tvs[i]->data) + in_offset_elems * elt_stride;
                uint8_t* d_dst = d_out + out_offset_elems * elt_stride;
                if (stream) {
                    cudaMemcpyAsync(d_dst, d_src, copy_elems * elt_stride, cudaMemcpyDeviceToDevice, stream);
                } else {
                    cudaMemcpy(d_dst, d_src, copy_elems * elt_stride, cudaMemcpyDeviceToDevice);
                }
            }
        }
        if (stream) { cudaStreamSynchronize(stream); }
        va::core::TensorView tv;
        tv.data = d_out; tv.shape = out_shape; tv.dtype = va::core::DType::F32; tv.on_gpu = true;
        p.tensors[out_key_] = tv;
        return true;
#else
        (void)ctx; // silence
        VA_LOG_C(::va::core::LogLevel::Warn, "ms.join") << "CUDA not available; falling back to CPU";
#endif
    }
    // CPU path
    size_t out_elems = 1; for (auto d: out_shape) out_elems *= (size_t)(d>0?d:1);
    host_buffer_.assign(out_elems, 0.0f);
    float* h_out = host_buffer_.data();
    for (size_t outer = 0; outer < block_before; ++outer) {
        for (size_t i=0;i<tvs.size();++i) {
            size_t copy_elems = axis_sizes[i] * block_after;
            size_t in_offset_elems = outer * axis_sizes[i] * block_after;
            size_t out_offset_elems = outer * out_axis * block_after + axis_offsets[i] * block_after;
            const float* src = static_cast<const float*>(tvs[i]->data) + in_offset_elems;
            float* dst = h_out + out_offset_elems;
            std::memcpy(dst, src, copy_elems * elt_stride);
        }
    }
    va::core::TensorView tv;
    tv.data = h_out; tv.shape = out_shape; tv.dtype = va::core::DType::F32; tv.on_gpu = false;
    p.tensors[out_key_] = tv;
    return true;
}

} } } // namespace
