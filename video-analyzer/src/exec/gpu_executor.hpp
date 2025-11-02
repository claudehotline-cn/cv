#pragma once

#include "exec/hooked_executor.hpp"
#include "utils/cuda_ctx_guard.hpp"

namespace va { namespace exec {

inline HookedExecutor& gpu_executor() {
    static HookedExecutor ex(
        /*workers*/ 4,
        /*maxQueue*/ 256,
        ExecutorOptions{
            // Thread init: bind CUDA context (device 0 by default)
            [](){ va::utils::ensure_cuda_ready(0); },
            // Thread fini: no-op for now
            [](){}
        }
    );
    return ex;
}

} } // namespace va::exec

