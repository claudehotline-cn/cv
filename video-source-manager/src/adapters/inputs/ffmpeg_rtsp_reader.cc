#include "adapters/inputs/ffmpeg_rtsp_reader.h"
#include <chrono>

namespace vsm {

bool FfmpegRtspReader::Start() {
  if (running_) return true;
  running_ = true;
  th_ = std::thread(&FfmpegRtspReader::Loop, this);
  return true;
}

void FfmpegRtspReader::Stop() {
  if (!running_) return;
  running_ = false;
  if (th_.joinable()) th_.join();
}

void FfmpegRtspReader::Loop() {
  cv::VideoCapture cap;
  if (!cap.open(uri_)) {
    running_ = false; return;
  }
  cv::Mat frame;
  auto last = std::chrono::steady_clock::now();
  uint64_t cnt = 0;
  while (running_) {
    if (!cap.read(frame)) { std::this_thread::sleep_for(std::chrono::milliseconds(10)); continue; }
    cnt++;
    auto now = std::chrono::steady_clock::now();
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(now - last).count();
    if (ms >= 1000) {
      fps_.store(static_cast<double>(cnt) * 1000.0 / static_cast<double>(ms));
      cnt = 0; last = now;
    }
  }
  cap.release();
}

} // namespace vsm

