#include "core/pipeline.hpp"

#include "analyzer/analyzer.hpp"
#include "media/source.hpp"
#include "media/encoder.hpp"
#include "media/transport.hpp"
#include "core/logger.hpp"

#include <chrono>
#include <thread>

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
    }
    return ok;
}

bool Pipeline::processFrame(const core::Frame& in) {
    if (!analyzer_) {
        return false;
    }

    core::Frame analyzed;
    if (!analyzer_->analyze(in, analyzed)) {
        VA_LOG_DEBUG() << "[Pipeline] analyze() returned false";
        return false;
    }
    // Ensure analyzed frame carries metrics sink
    if (!analyzed.zc) analyzed.zc = &zc_metrics_;

    va::media::IEncoder::Packet packet;
    if (encoder_) {
        if (!encoder_->encode(analyzed, packet)) {
            VA_LOG_DEBUG() << "[Pipeline] encoder.encode returned false";
            return false;
        }
        if (transport_ && !packet.data.empty()) {
            transport_->send(track_id_, packet.data.data(), packet.data.size());
        }
    }
    return true;
}

} // namespace va::core
