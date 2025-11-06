#include "core/pipeline.hpp"

#include "analyzer/analyzer.hpp"
#include "media/source.hpp"
#include "media/encoder.hpp"
#include "media/transport.hpp"
#include "core/logger.hpp"
#include "utils/cuda_ctx_guard.hpp"

#include <chrono>
#include <thread>
#include <cstdlib>

namespace va::core {

Pipeline::Pipeline(std::shared_ptr<va::media::ISwitchableSource> source,
                   std::shared_ptr<va::analyzer::Analyzer> analyzer,
                   std::shared_ptr<va::media::IEncoder> encoder,
                   std::shared_ptr<va::media::ITransport> transport,
                   std::string stream_id,
                   std::string profile_id)
    : source_(std::move(source)),
      analyzer_(std::move(analyzer)),
      encoder_(std::move(encoder)),
      transport_(std::move(transport)),
      stream_id_(std::move(stream_id)),
      profile_id_(std::move(profile_id)) {
    track_id_ = stream_id_ + ":" + profile_id_;
}

Pipeline::~Pipeline() {
    stop();
}

void Pipeline::start() {
    bool expected = false;
    if (!running_.compare_exchange_strong(expected, true)) {
        return;
    }

    processed_frames_.store(0);
    dropped_frames_.store(0);
    avg_latency_ms_.store(0.0);
    fps_.store(0.0);
    last_timestamp_ms_.store(0.0);

    if (source_) {
        try {
            source_->start();
        } catch (const std::exception& ex) {
            VA_LOG_ERROR() << "[Pipeline] source start exception: " << ex.what();
        } catch (...) {
            VA_LOG_ERROR() << "[Pipeline] source start unknown exception";
        }
    }

    try {
        worker_ = std::thread(&Pipeline::run, this);
    } catch (const std::exception& ex) {
        VA_LOG_ERROR() << "[Pipeline] failed to start worker thread: " << ex.what();
        running_.store(false);
    } catch (...) {
        VA_LOG_ERROR() << "[Pipeline] failed to start worker thread: unknown error";
        running_.store(false);
    }
}

void Pipeline::stop() {
    bool expected = true;
    if (!running_.compare_exchange_strong(expected, false)) {
        return;
    }

    if (worker_.joinable()) {
        worker_.join();
    }

    if (source_) {
        source_->stop();
    }

    if (encoder_) {
        encoder_->close();
    }
    if (transport_) {
        transport_->disconnect();
    }
}

bool Pipeline::isRunning() const {
    return running_.load();
}

va::media::ISwitchableSource* Pipeline::source() {
    return source_.get();
}

va::analyzer::Analyzer* Pipeline::analyzer() {
    return analyzer_.get();
}

Pipeline::Metrics Pipeline::metrics() const {
    Metrics m;
    m.fps = fps_.load();
    m.avg_latency_ms = avg_latency_ms_.load();
    m.last_processed_ms = last_timestamp_ms_.load();
    m.processed_frames = processed_frames_.load();
    m.dropped_frames = dropped_frames_.load();
    return m;
}

void Pipeline::recordFrameProcessed(double latency_ms) {
    const auto frames = processed_frames_.fetch_add(1) + 1;

    const double prev_avg = avg_latency_ms_.load();
    const double new_avg = prev_avg + (latency_ms - prev_avg) / static_cast<double>(frames);
    avg_latency_ms_.store(new_avg);

    const double now_ms = ms_now();
    const double last_ms = last_timestamp_ms_.load();
    last_timestamp_ms_.store(now_ms);

    // record end-to-end latency histogram
    latency_hist_.add(latency_ms);

    if (last_ms > 0.0) {
        const double delta = now_ms - last_ms;
        if (delta > 0.0) {
            const double inst_fps = 1000.0 / delta;
            const double prev_fps = fps_.load();
            const double blended = prev_fps + (inst_fps - prev_fps) / 10.0;
            fps_.store(blended);
        }
    }
}

void Pipeline::recordFrameDropped() {
    dropped_frames_.fetch_add(1);
    last_timestamp_ms_.store(ms_now());
}

va::media::ITransport::Stats Pipeline::transportStats() const {
    if (!transport_) {
        return {};
    }
    return transport_->stats();
}

void Pipeline::run() {
    // Ensure this worker thread is CUDA-ready if GPU will be used downstream.
    va::utils::ensure_cuda_ready(0);
    while (running_.load()) {
        try {
            core::Frame frame;
            if (!pullFrame(frame)) {
                std::this_thread::sleep_for(std::chrono::milliseconds(10));
                continue;
            }

            const double start_ms = ms_now();
            if (processFrame(frame)) {
                const double latency_ms = ms_now() - start_ms;
                recordFrameProcessed(latency_ms);
            } else {
                recordFrameDropped();
            }
        } catch (const std::exception& ex) {
            VA_LOG_ERROR() << "[Pipeline] unhandled exception in run loop: " << ex.what();
            recordFrameDropped();
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        } catch (...) {
            VA_LOG_ERROR() << "[Pipeline] unknown exception in run loop";
            recordFrameDropped();
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
    }
}

bool Pipeline::pullFrame(core::Frame& frame) {
    if (!source_) {
        return false;
    }
    bool ok = source_->read(frame);
    if (ok) {
        frame.pts_ms = ms_now();
        frame.zc = &zc_metrics_;
        frame.lat = &latency_sink_;
    }
    return ok;
}

bool Pipeline::processFrame(const core::Frame& in) {
    if (!analyzer_) {
        return false;
    }

    // Pause mode: bypass analysis/overlay, encode raw frame under SAME key (track_id_)
    if (!analysis_enabled_.load(std::memory_order_relaxed)) {
        if (encoder_ && transport_) {
            va::media::IEncoder::Packet packet;
            auto t0 = std::chrono::high_resolution_clock::now();
            if (force_idr_next_.exchange(false)) {
                VA_LOG_INFO() << "[Pipeline] force next frame IDR (mode switch) key='" << track_id_ << "'";
                try { encoder_->requestKeyframe(); } catch (...) {}
            }
            if (encoder_->encode(in, packet)) {
                auto t1 = std::chrono::high_resolution_clock::now();
                auto ms = [](auto a, auto b){ return std::chrono::duration_cast<std::chrono::milliseconds>(b-a).count(); };
                if (in.lat) in.lat->record_encode_ms(static_cast<double>(ms(t0, t1)));
                if (!packet.data.empty()) {
                    transport_->send(track_id_, packet.data.data(), packet.data.size());
                }
                return true;
            }
        }
        return false;
    }

    core::Frame analyzed;
    // Optional: publish source-level raw frame (base key = stream_id_) before overlay
    try {
        const char* v = std::getenv("VA_PUBLISH_RAW_BASE");
        bool publish_raw = false; // default off (single-key design)
        if (v) {
            std::string s(v); for (auto& c : s) c = (char)std::tolower(c);
            publish_raw = (s=="1" || s=="true" || s=="yes" || s=="on");
        }
        if (publish_raw && encoder_ && transport_) {
            va::media::IEncoder::Packet raw_packet;
            if (encoder_->encode(in, raw_packet)) {
                if (!raw_packet.data.empty()) {
                    const std::string base_track = stream_id_;
                    transport_->send(base_track, raw_packet.data.data(), raw_packet.data.size());
                }
            }
        }
    } catch (...) { /* best-effort */ }
    // Use virtual IFrameFilter::process to allow multistage adapter to take effect
    if (!analyzer_->process(in, analyzed)) {
        // 分析暂不可用（例如首次构建 TensorRT 引擎期间）：
        // 为避免前端画面卡住，这里回退为原始帧直通编码与发送。
        VA_LOG_DEBUG() << "[Pipeline] analyze() returned false -> passthrough raw frame";
        if (encoder_ && transport_) {
            va::media::IEncoder::Packet packet;
            auto t0 = std::chrono::high_resolution_clock::now();
            if (force_idr_next_.exchange(false)) {
                VA_LOG_INFO() << "[Pipeline] force next frame IDR (analyze not-ready) key='" << track_id_ << "'";
                try { encoder_->requestKeyframe(); } catch (...) {}
            }
            if (encoder_->encode(in, packet)) {
                auto t1 = std::chrono::high_resolution_clock::now();
                auto ms = [](auto a, auto b){ return std::chrono::duration_cast<std::chrono::milliseconds>(b-a).count(); };
                if (in.lat) in.lat->record_encode_ms(static_cast<double>(ms(t0, t1)));
                if (!packet.data.empty()) {
                    transport_->send(track_id_, packet.data.data(), packet.data.size());
                }
                return true;
            }
        }
        return false;
    }
    // Ensure analyzed frame carries metrics sink
    if (!analyzed.zc) analyzed.zc = &zc_metrics_;
    if (!analyzed.lat) analyzed.lat = &latency_sink_;

    va::media::IEncoder::Packet packet;
    if (encoder_) {
        auto tenc0 = std::chrono::high_resolution_clock::now();
        if (force_idr_next_.exchange(false)) {
            VA_LOG_INFO() << "[Pipeline] force next frame IDR (mode switch) key='" << track_id_ << "'";
            try { encoder_->requestKeyframe(); } catch (...) {}
        }
        if (!encoder_->encode(analyzed, packet)) {
            VA_LOG_DEBUG() << "[Pipeline] encoder.encode returned false";
            return false;
        }
        auto tenc1 = std::chrono::high_resolution_clock::now();
        auto ms = [](auto a, auto b){ return std::chrono::duration_cast<std::chrono::milliseconds>(b-a).count(); };
        if (analyzed.lat) analyzed.lat->record_encode_ms(static_cast<double>(ms(tenc0, tenc1)));
        if (transport_ && !packet.data.empty()) {
            transport_->send(track_id_, packet.data.data(), packet.data.size());
        }
    }
    return true;
}

void Pipeline::setAnalysisEnabled(bool enabled) {
    const bool prev = analysis_enabled_.exchange(enabled, std::memory_order_relaxed);
    force_idr_next_.store(true, std::memory_order_relaxed);
    if (prev != enabled) {
        VA_LOG_INFO() << "[Pipeline] analysis mode -> " << (enabled ? "ON" : "OFF")
                      << " key='" << track_id_ << "' stream='" << stream_id_ << "' profile='" << profile_id_ << "'";
    } else {
        VA_LOG_DEBUG() << "[Pipeline] analysis mode unchanged (" << (enabled?"ON":"OFF")
                       << ") key='" << track_id_ << "'";
    }
}

Pipeline::LatencySnapshot Pipeline::latencyHist() const {
    LatencySnapshot snap;
    latency_hist_.snapshot(snap);
    return snap;
}

Pipeline::StageLatencySnapshot Pipeline::stageLatency() const {
    StageLatencySnapshot out;
    preproc_hist_.snapshot(out.preproc);
    infer_hist_.snapshot(out.infer);
    postproc_hist_.snapshot(out.postproc);
    encode_hist_.snapshot(out.encode);
    return out;
}

} // namespace va::core
