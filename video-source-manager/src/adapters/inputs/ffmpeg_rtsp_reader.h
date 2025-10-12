#pragma once

#include <string>
#include <thread>
#include <atomic>
#include <opencv2/opencv.hpp>

namespace vsm {

class FfmpegRtspReader {
public:
  explicit FfmpegRtspReader(std::string uri) : uri_(std::move(uri)) {}
  ~FfmpegRtspReader() { Stop(); }

  bool Start();
  void Stop();
  double Fps() const { return fps_; }

private:
  void Loop();
  std::string uri_;
  std::thread th_;
  std::atomic<bool> running_{false};
  std::atomic<double> fps_{0.0};
};

} // namespace vsm

