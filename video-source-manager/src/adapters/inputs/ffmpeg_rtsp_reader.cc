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
  // basic jitter estimation: stddev of inter-frame interval within the last second window
  double sum = 0.0, sum2 = 0.0; int n = 0; auto win_start = last;
  while (running_) {
    if (!cap.read(frame)) { std::this_thread::sleep_for(std::chrono::milliseconds(10)); continue; }
    cnt++;
    last_ok_unix_sec_.store(static_cast<uint64_t>(std::time(nullptr)));
    auto now = std::chrono::steady_clock::now();
    auto dt_ms = std::chrono::duration_cast<std::chrono::milliseconds>(now - last).count();
    // accumulate window
    sum += (double)dt_ms; sum2 += (double)dt_ms * (double)dt_ms; n++;
    auto win_ms = std::chrono::duration_cast<std::chrono::milliseconds>(now - win_start).count();
    if (win_ms >= 1000) {
      double mean = (n>0)? sum / (double)n : 0.0;
      double var = (n>1)? std::max(0.0, sum2/(double)n - mean*mean) : 0.0;
      double jitter = std::sqrt(var);
      double fps = (win_ms>0)? (double)cnt * 1000.0 / (double)win_ms : 0.0;
      fps_.store(fps);
      jitter_ms_.store(jitter);
      // rtt/loss are placeholders (no RTCP here); keep 0 and derive loss by fps drop if severe
      if (fps < 1.0) {
        loss_ratio_.store(1.0);
      } else {
        loss_ratio_.store(0.0);
      }
      // reset window
      cnt = 0; sum = 0.0; sum2 = 0.0; n = 0; win_start = now; last = now;
    } else {
      last = now;
    }
  }
  cap.release();
}

} // namespace vsm
