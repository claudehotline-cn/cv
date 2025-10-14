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
  const std::string& Uri() const { return uri_; }
  double JitterMs() const { return jitter_ms_; }
  double RttMs() const { return rtt_ms_; }
  double LossRatio() const { return loss_ratio_; }
  uint64_t LastOkUnixSec() const { return last_ok_unix_sec_; }
  int Width() const { return width_.load(); }
  int Height() const { return height_.load(); }
  const std::string& Codec() const { return codec_; }
  const std::string& PixFmt() const { return pix_fmt_; }
  const std::string& ColorSpace() const { return color_space_; }

private:
  void Loop();
  std::string uri_;
  std::thread th_;
  std::atomic<bool> running_{false};
  std::atomic<double> fps_{0.0};
  std::atomic<double> jitter_ms_{0.0};
  std::atomic<double> rtt_ms_{0.0};
  std::atomic<double> loss_ratio_{0.0};
  std::atomic<uint64_t> last_ok_unix_sec_{0};
  std::atomic<int> width_{0};
  std::atomic<int> height_{0};
  std::string codec_;
  std::string pix_fmt_ {"BGR"};
  std::string color_space_ {"BT.709"};
};

} // namespace vsm
