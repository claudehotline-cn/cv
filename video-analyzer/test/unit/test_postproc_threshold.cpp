#include "analyzer/postproc_yolo_det.hpp"
#include "analyzer/interfaces.hpp"

#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <vector>

#ifdef _WIN32
#include <cstdlib>
static void set_env(const char* k, const char* v) { _putenv_s(k, v); }
#else
#include <unistd.h>
static void set_env(const char* k, const char* v) { setenv(k, v, 1); }
#endif

using va::analyzer::YoloDetectionPostprocessor;
using va::core::TensorView;
using va::core::LetterboxMeta;
using va::core::ModelOutput;

static TensorView make_tensor(std::vector<float>& storage) {
    // Layout: [1, N, 5] where each det is [cx, cy, w, h, score] with 1 class
    const int N = 2; const int A = 5;
    storage.resize(static_cast<size_t>(N * A));
    // det0: score 0.20
    storage[0*A + 0] = 100.0f; // cx
    storage[0*A + 1] = 100.0f; // cy
    storage[0*A + 2] = 50.0f;  // w
    storage[0*A + 3] = 50.0f;  // h
    storage[0*A + 4] = 0.20f;  // score
    // det1: score 0.50
    storage[1*A + 0] = 200.0f;
    storage[1*A + 1] = 200.0f;
    storage[1*A + 2] = 60.0f;
    storage[1*A + 3] = 60.0f;
    storage[1*A + 4] = 0.50f;

    TensorView t;
    t.data = storage.data();
    t.shape = {1, N, A};
    t.dtype = va::core::DType::F32;
    t.on_gpu = false;
    return t;
}

int main() {
    // Prepare synthetic tensor
    std::vector<float> buf;
    TensorView tv = make_tensor(buf);
    std::vector<TensorView> outputs{tv};

    LetterboxMeta meta;
    meta.scale = 1.0f; meta.pad_x = 0; meta.pad_y = 0;
    meta.input_width = 640; meta.input_height = 640;
    meta.original_width = 640; meta.original_height = 640;

    YoloDetectionPostprocessor pp;
    ModelOutput out;

    // Case 1: threshold = 0.25 (default) -> expect only det with 0.50 kept (size=1)
    set_env("VA_CONF_THRESH", "0.25");
    out.boxes.clear(); out.masks.clear();
    if (!pp.run(outputs, meta, out)) {
        std::cerr << "postprocessor run failed at case1" << std::endl;
        return 1;
    }
    if (out.boxes.size() != 1) {
        std::cerr << "expected 1 box at thr=0.25, got " << out.boxes.size() << std::endl;
        return 2;
    }

    // Case 2: threshold = 0.10 -> expect both kept (size=2)
    set_env("VA_CONF_THRESH", "0.10");
    out.boxes.clear(); out.masks.clear();
    if (!pp.run(outputs, meta, out)) {
        std::cerr << "postprocessor run failed at case2" << std::endl;
        return 3;
    }
    if (out.boxes.size() != 2) {
        std::cerr << "expected 2 boxes at thr=0.10, got " << out.boxes.size() << std::endl;
        return 4;
    }

    std::cout << "OK: threshold override works (0.25->1 box, 0.10->2 boxes)." << std::endl;
    return 0;
}

