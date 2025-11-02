#include "server/rest_impl.hpp"
#include "analyzer/model_registry.hpp"
#include "server/sse_metrics.hpp"
#include "core/codec_registry.hpp"
#include "core/wal.hpp"
#include <map>

namespace va::server {

HttpResponse RestServer::Impl::handleMetrics(const HttpRequest& /*req*/) {
    // Prometheus text exposition format (0.0.4)
    auto sys = app.systemStats();
    auto gm = va::core::GlobalMetrics::snapshot();
    const auto& obs = app.appConfig().observability;
    const bool use_registry = metrics_registry_enabled_.has_value() ? *metrics_registry_enabled_ : obs.metrics_registry_enabled;
    if (use_registry) {
        va::core::MetricsTextBuilder mb;
        // System metrics
        mb.header("va_pipelines_total", "gauge", "Total pipelines");
        mb.sample("va_pipelines_total", "{}", std::to_string(static_cast<unsigned long long>(sys.total_pipelines)));
        mb.header("va_pipelines_running", "gauge", "Running pipelines");
        mb.sample("va_pipelines_running", "{}", std::to_string(static_cast<unsigned long long>(sys.running_pipelines)));
        mb.header("va_pipeline_aggregate_fps", "gauge", "Aggregate FPS across pipelines");
        mb.sample("va_pipeline_aggregate_fps", "{}", sys.aggregate_fps);

        mb.header("va_frames_processed_total", "counter", "Frames processed (sum)");
        mb.sample("va_frames_processed_total", "{}", std::to_string(static_cast<unsigned long long>(sys.processed_frames)));
        mb.header("va_frames_dropped_total", "counter", "Frames dropped (sum)");
        mb.sample("va_frames_dropped_total", "{}", std::to_string(static_cast<unsigned long long>(sys.dropped_frames)));

        mb.header("va_transport_packets_total", "counter", "Transport packets sent (sum)");
        mb.sample("va_transport_packets_total", "{}", std::to_string(static_cast<unsigned long long>(sys.transport_packets)));
        mb.header("va_transport_bytes_total", "counter", "Transport bytes sent (sum)");
        mb.sample("va_transport_bytes_total", "{}", std::to_string(static_cast<unsigned long long>(sys.transport_bytes)));

        mb.header("va_d2d_nv12_frames_total", "counter", "NVENC device NV12 direct-feed frames");
        mb.sample("va_d2d_nv12_frames_total", "{}", std::to_string(static_cast<unsigned long long>(gm.d2d_nv12_frames)));
        mb.header("va_cpu_fallback_skips_total", "counter", "CPU upload skipped (device NV12 path)");
        mb.sample("va_cpu_fallback_skips_total", "{}", std::to_string(static_cast<unsigned long long>(gm.cpu_fallback_skips)));
        mb.header("va_encoder_eagain_retry_total", "counter", "Encoder EAGAIN drain+retry occurrences");
        mb.sample("va_encoder_eagain_retry_total", "{}", std::to_string(static_cast<unsigned long long>(gm.eagain_retry_count)));
        mb.header("va_overlay_nv12_kernel_hits_total", "counter", "NV12 kernel overlay executions");
        mb.sample("va_overlay_nv12_kernel_hits_total", "{}", std::to_string(static_cast<unsigned long long>(gm.overlay_nv12_kernel_hits)));
        mb.header("va_overlay_nv12_passthrough_total", "counter", "NV12 overlay passthrough (no boxes)");
        mb.sample("va_overlay_nv12_passthrough_total", "{}", std::to_string(static_cast<unsigned long long>(gm.overlay_nv12_passthrough)));
        // Control-plane metrics
        mb.header("va_cp_auto_subscribe_total", "counter", "Auto subscribe events (success)");
        mb.sample("va_cp_auto_subscribe_total", "{}", std::to_string(static_cast<unsigned long long>(gm.cp_auto_subscribe_total)));
        mb.header("va_cp_auto_unsubscribe_total", "counter", "Auto unsubscribe events (success)");
        mb.sample("va_cp_auto_unsubscribe_total", "{}", std::to_string(static_cast<unsigned long long>(gm.cp_auto_unsubscribe_total)));
        mb.header("va_cp_auto_switch_source_total", "counter", "Auto source switch events (success)");
        mb.sample("va_cp_auto_switch_source_total", "{}", std::to_string(static_cast<unsigned long long>(gm.cp_auto_switch_source_total)));
        mb.header("va_cp_auto_switch_model_total", "counter", "Auto model switch events (success)");
        mb.sample("va_cp_auto_switch_model_total", "{}", std::to_string(static_cast<unsigned long long>(gm.cp_auto_switch_model_total)));
        mb.header("va_cp_auto_subscribe_failed_total", "counter", "Auto subscribe failures");
        mb.sample("va_cp_auto_subscribe_failed_total", "{}", std::to_string(static_cast<unsigned long long>(gm.cp_auto_subscribe_failed_total)));
        mb.header("va_cp_auto_switch_source_failed_total", "counter", "Auto source switch failures");
        mb.sample("va_cp_auto_switch_source_failed_total", "{}", std::to_string(static_cast<unsigned long long>(gm.cp_auto_switch_source_failed_total)));
        mb.header("va_cp_auto_switch_model_failed_total", "counter", "Auto model switch failures");
        mb.sample("va_cp_auto_switch_model_failed_total", "{}", std::to_string(static_cast<unsigned long long>(gm.cp_auto_switch_model_failed_total)));

        // Helper functions
        auto classify_path = [](const va::core::TrackManager::PipelineInfo& info) -> std::string {
            if (info.zc.d2d_nv12_frames > 0) return "d2d";
            std::string lower = info.encoder_cfg.codec;
            std::transform(lower.begin(), lower.end(), lower.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
            if (lower.find("nvenc") != std::string::npos) return "gpu";
            return "cpu";
        };
        const bool ext_labels = metrics_extended_labels_.has_value() ? *metrics_extended_labels_ : obs.metrics_extended_labels;
        auto lbl = [&](const va::core::TrackManager::PipelineInfo& pinfo, const std::string& path) {
            std::ostringstream oss;
            oss << "{source_id=\"" << pinfo.stream_id << "\",path=\"" << path << "\"";
            if (ext_labels) {
                if (!pinfo.decoder_label.empty()) oss << ",decoder=\"" << pinfo.decoder_label << "\"";
                if (!pinfo.encoder_cfg.codec.empty()) oss << ",encoder=\"" << pinfo.encoder_cfg.codec << "\"";
                std::string preproc = "cpu";
                auto eng = app.currentEngine();
                auto it = eng.options.find("use_cuda_preproc");
                if (it != eng.options.end()) {
                    std::string v = toLower(it->second);
                    if (v=="1"||v=="true"||v=="yes"||v=="on") preproc = "cuda";
                }
                oss << ",preproc=\"" << preproc << "\"";
            }
            oss << "}"; return oss.str(); };

        // Per-source FPS and frames
        mb.header("va_pipeline_fps", "gauge", "Pipeline FPS per source");
        for (const auto& info : app.pipelines()) {
            const std::string path = classify_path(info);
            mb.sample("va_pipeline_fps", lbl(info, path), info.metrics.fps);
        }
        mb.header("va_frames_processed_total", "counter", "Frames processed per source");
        mb.header("va_frames_dropped_total", "counter", "Frames dropped per source");
        for (const auto& info : app.pipelines()) {
            const std::string path = classify_path(info);
            mb.sample("va_frames_processed_total", lbl(info, path), info.metrics.processed_frames);
            mb.sample("va_frames_dropped_total", lbl(info, path), info.metrics.dropped_frames);
        }

        // Histograms (per stage)
        mb.header("va_frame_latency_ms", "histogram", "Frame processing latency per stage");
        const double bounds_ms[10] = {1,2,5,10,20,50,100,200,500,1000};
        auto emit_hist = [&](const std::string& stage,
                             const va::core::TrackManager::PipelineInfo& info,
                             const va::core::Pipeline::LatencySnapshot& snap) {
            const std::string path = classify_path(info);
            uint64_t cumulative = 0;
            for (int i=0;i<va::core::Pipeline::LatencySnapshot::kNumBuckets; ++i) {
                cumulative += snap.buckets[i];
                std::ostringstream ls; ls<<"{stage=\""<<stage<<"\",source_id=\""<<info.stream_id<<"\",path=\""<<path<<"\",le=\""<<bounds_ms[i]<<"\"}";
                mb.sample("va_frame_latency_ms_bucket", ls.str(), cumulative);
            }
            std::ostringstream linf; linf<<"{stage=\""<<stage<<"\",source_id=\""<<info.stream_id<<"\",path=\""<<path<<"\",le=\"+Inf\"}";
            mb.sample("va_frame_latency_ms_bucket", linf.str(), snap.count);
            double sum_ms = static_cast<double>(snap.sum_us) / 1000.0;
            std::ostringstream lsum; lsum<<"{stage=\""<<stage<<"\",source_id=\""<<info.stream_id<<"\",path=\""<<path<<"\"}";
            mb.sample("va_frame_latency_ms_sum", lsum.str(), sum_ms);
            mb.sample("va_frame_latency_ms_count", lsum.str(), snap.count);
        };
        for (const auto& info : app.pipelines()) {
            emit_hist("preproc", info, info.stage_latency.preproc);
            emit_hist("infer",   info, info.stage_latency.infer);
            emit_hist("postproc",info, info.stage_latency.postproc);
            emit_hist("encode",  info, info.stage_latency.encode);
        }

        // Drop reasons
        mb.header("va_frames_dropped_total", "counter", "Frames dropped by reason");
        for (const auto& row : va::core::DropMetrics::snapshot()) {
            auto emit = [&](const char* reason, uint64_t v) { if(!v) return; std::ostringstream ls; ls<<"{source_id=\""<<row.source_id<<"\",reason=\""<<reason<<"\"}"; mb.sample("va_frames_dropped_total", ls.str(), v);};
            emit("queue_overflow", row.counters.queue_overflow);
            emit("decode_error",   row.counters.decode_error);
            emit("encode_eagain",  row.counters.encode_eagain);
            emit("backpressure",   row.counters.backpressure);
        }

        // Encoder per-source
        mb.header("va_encoder_packets_total", "counter", "Encoded packets per source");
        mb.header("va_encoder_bytes_total", "counter", "Encoded bytes per source");
        mb.header("va_encoder_eagain_total", "counter", "Encoder EAGAIN occurrences per source");
        for (const auto& info : app.pipelines()) {
            const std::string path = classify_path(info);
            std::ostringstream ls; ls<<"{source_id=\""<<info.stream_id<<"\",path=\""<<path<<"\"";
            if (ext_labels && !info.encoder_cfg.codec.empty()) ls<<",encoder=\""<<info.encoder_cfg.codec<<"\"";
            if (ext_labels && !info.decoder_label.empty()) ls<<",decoder=\""<<info.decoder_label<<"\"";
            ls<<"}";
            mb.sample("va_encoder_packets_total", ls.str(), info.transport_stats.packets);
            mb.sample("va_encoder_bytes_total", ls.str(), info.transport_stats.bytes);
            mb.sample("va_encoder_eagain_total", ls.str(), info.zc.eagain_retry_count);
        }

        // Reconnects & NVDEC
        mb.header("va_rtsp_source_reconnects_total", "counter", "RTSP source reconnects");
        for (const auto& row : va::core::SourceReconnects::snapshot()) {
            std::ostringstream ls; ls<<"{source_id=\""<<row.source_id<<"\"}"; mb.sample("va_rtsp_source_reconnects_total", ls.str(), row.reconnects);
        }
        mb.header("va_nvdec_device_recover_total", "counter", "NVDEC device-path recovery events");
        mb.header("va_nvdec_await_idr_total", "counter", "NVDEC await-IDR occurrences (startup/reopen)");
        for (const auto& row : va::core::NvdecEvents::snapshot()) {
            std::ostringstream ls; ls<<"{source_id=\""<<row.source_id<<"\"}";
            mb.sample("va_nvdec_device_recover_total", ls.str(), row.device_recover);
            mb.sample("va_nvdec_await_idr_total", ls.str(), row.await_idr);
        }

        // Control-plane request metrics (from registry)
        mb.header("va_cp_requests_total", "counter", "Control-plane requests total by op/code");
        {
            std::lock_guard<std::mutex> lk(cp_mu);
            for (const auto& kv : cp_totals_by_code) {
                const std::string& op = kv.first;
                for (const auto& kv2 : kv.second) {
                    std::ostringstream ls; ls << "{op=\"" << op << "\",code=\"" << kv2.first << "\"}";
                    mb.sample("va_cp_requests_total", ls.str(), static_cast<uint64_t>(kv2.second));
                }
            }
            // Histogram: duration seconds per op
            mb.header("va_cp_request_duration_seconds", "histogram", "Control-plane request duration (s)");
            for (const auto& kvh : cp_hist_buckets) {
                const std::string& op = kvh.first;
                double sum = cp_hist_sum.count(op)? cp_hist_sum.at(op) : 0.0;
                unsigned long long cnt = cp_hist_count.count(op)? cp_hist_count.at(op) : 0ULL;
                // cumulative buckets
                unsigned long long acc = 0ULL;
                for (size_t i=0;i<cp_bounds.size();++i) {
                    acc += kvh.second[i];
                    std::ostringstream ls; ls << "{op=\""<<op<<"\",le=\""<<cp_bounds[i]<<"\"}";
                    mb.sample("va_cp_request_duration_seconds_bucket", ls.str(), static_cast<uint64_t>(acc));
                }
                // +Inf bucket
                std::ostringstream lsi; lsi << "{op=\""<<op<<"\",le=\"+Inf\"}"; mb.sample("va_cp_request_duration_seconds_bucket", lsi.str(), static_cast<uint64_t>(cnt));
                // _sum and _count
                std::ostringstream lsn; lsn << "{op=\""<<op<<"\"}";
                mb.sample("va_cp_request_duration_seconds_sum", lsn.str(), sum);
                mb.sample("va_cp_request_duration_seconds_count", lsn.str(), static_cast<uint64_t>(cnt));
            }
        }

        // WAL/Restart metrics (M1)
        try {
            mb.header("va_wal_failed_restart_total", "counter", "Subscriptions inflight before last restart (from WAL)");
            mb.sample("va_wal_failed_restart_total", "{}", static_cast<uint64_t>(va::core::wal::failedRestartCount()));
            // Minimal dimension labels for WAL: feature-enabled gauge（基数受控）
            mb.header("va_feature_enabled", "gauge", "Feature toggle enabled (1/0)");
            mb.sample("va_feature_enabled", "{feature=\"wal\"}", static_cast<uint64_t>(va::core::wal::enabled() ? 1 : 0));
            // Mirror tail-derived WAL event counters (best-effort, low cardinality)
            try {
                auto lines = va::core::wal::tail(200);
                unsigned long long c_enqueue = 0ULL, c_ready = 0ULL, c_failed = 0ULL, c_cancelled = 0ULL, c_restart = 0ULL;
                for (const auto& s : lines) {
                    if (s.find("\"op\":\"enqueue\"") != std::string::npos) c_enqueue++;
                    else if (s.find("\"op\":\"ready\"") != std::string::npos) c_ready++;
                    else if (s.find("\"op\":\"failed\"") != std::string::npos) c_failed++;
                    else if (s.find("\"op\":\"cancelled\"") != std::string::npos) c_cancelled++;
                    else if (s.find("\"op\":\"restart\"") != std::string::npos) c_restart++;
                }
                mb.header("va_wal_events_total", "counter", "WAL events observed from tail (best-effort)");
                auto emit = [&](const char* op, unsigned long long v){ std::ostringstream ls; ls<<"{op=\""<<op<<"\"}"; mb.sample("va_wal_events_total", ls.str(), static_cast<uint64_t>(v)); };
                emit("enqueue", c_enqueue); emit("ready", c_ready); emit("failed", c_failed); emit("cancelled", c_cancelled); emit("restart", c_restart);
            } catch (...) {}
        } catch (...) {}

        // Model registry preheat & cache metrics (M1/M2)
        try {
            auto& mr = va::analyzer::ModelRegistry::instance();
            auto rs = mr.metricsSnapshot();
            mb.header("va_model_preheat_enabled", "gauge", "Model preheat enabled (1/0)");
            mb.sample("va_model_preheat_enabled", "{}", static_cast<uint64_t>(rs.enabled ? 1 : 0));
            mb.header("va_model_preheat_concurrency", "gauge", "Model preheat concurrency");
            mb.sample("va_model_preheat_concurrency", "{}", static_cast<uint64_t>(rs.concurrency));
            mb.header("va_model_preheat_warmed_total", "gauge", "Models warmed (best-effort)");
            mb.sample("va_model_preheat_warmed_total", "{}", static_cast<uint64_t>(rs.warmed));
            // Cache metrics
            mb.header("va_model_cache_entries", "gauge", "Model registry cache entries");
            mb.sample("va_model_cache_entries", "{}", static_cast<uint64_t>(rs.cache_entries));
            mb.header("va_model_cache_new_total", "counter", "Model registry cache new entries");
            mb.sample("va_model_cache_new_total", "{}", static_cast<uint64_t>(rs.cache_new_total));
            mb.header("va_model_cache_touch_total", "counter", "Model registry cache touch (hits)");
            mb.sample("va_model_cache_touch_total", "{}", static_cast<uint64_t>(rs.cache_touch_total));
            mb.header("va_model_cache_evict_total", "counter", "Model registry cache evictions");
            mb.sample("va_model_cache_evict_total", "{}", static_cast<uint64_t>(rs.cache_evict_total));
            // duration histogram
            mb.header("va_model_preheat_duration_seconds", "histogram", "Per-model preheat duration (s)");
            unsigned long long accp = 0ULL;
            for (size_t i=0;i<rs.bounds.size(); ++i) { accp += (i<rs.bucket_counts.size()? rs.bucket_counts[i] : 0ULL); std::ostringstream ls; ls << "{le=\""<<rs.bounds[i]<<"\"}"; mb.sample("va_model_preheat_duration_seconds_bucket", ls.str(), static_cast<uint64_t>(accp)); }
            std::ostringstream lsi; lsi << "{le=\"+Inf\"}"; mb.sample("va_model_preheat_duration_seconds_bucket", lsi.str(), rs.duration_count);
            mb.sample("va_model_preheat_duration_seconds_sum", "{}", rs.duration_sum);
            mb.sample("va_model_preheat_duration_seconds_count", "{}", rs.duration_count);
            mb.header("va_model_preheat_failed_total", "counter", "Model preheat failures");
            mb.sample("va_model_preheat_failed_total", "{}", static_cast<uint64_t>(rs.failed_total));
        } catch (...) {}

        // Codec registry metrics (optional; metrics-only, no caching)
        try {
            auto cs = va::core::CodecRegistry::snapshot();
            mb.header("va_codec_decoder_build_total", "counter", "Decoder builds by impl");
            for (const auto& kv : cs.decoder_build_by_impl) { std::ostringstream ls; ls<<"{impl=\""<<kv.impl<<"\"}"; mb.sample("va_codec_decoder_build_total", ls.str(), kv.value); }
            mb.header("va_codec_decoder_hit_total", "counter", "Decoder cache hits by impl");
            for (const auto& kv : cs.decoder_hit_by_impl) { std::ostringstream ls; ls<<"{impl=\""<<kv.impl<<"\"}"; mb.sample("va_codec_decoder_hit_total", ls.str(), kv.value); }
            mb.header("va_codec_encoder_build_total", "counter", "Encoder builds by impl");
            for (const auto& kv : cs.encoder_build_by_impl) { std::ostringstream ls; ls<<"{impl=\""<<kv.impl<<"\"}"; mb.sample("va_codec_encoder_build_total", ls.str(), kv.value); }
            mb.header("va_codec_encoder_hit_total", "counter", "Encoder cache hits by impl");
            for (const auto& kv : cs.encoder_hit_by_impl) { std::ostringstream ls; ls<<"{impl=\""<<kv.impl<<"\"}"; mb.sample("va_codec_encoder_hit_total", ls.str(), kv.value); }
        } catch (...) {}

        // Subscription metrics
        if (lro_enabled_ && lro_runner_) {
            auto ms = lro_runner_->metricsSnapshot();
            mb.header("va_subscriptions_queue_length", "gauge", "Pending subscription tasks in queue");
            mb.sample("va_subscriptions_queue_length", "{}", static_cast<uint64_t>(ms.queue_length));
            // In-progress gauge (parity with plain-text branch)
            mb.header("va_subscriptions_in_progress", "gauge", "Non-terminal subscriptions in progress");
            mb.sample("va_subscriptions_in_progress", "{}", static_cast<uint64_t>(ms.in_progress));
            // Slots and backpressure (from admission snapshot in Impl)
            try {
                int s_open = 0, s_load = 0, s_start = 0; int fairw = 0;
                if (lro_admission_) {
                    auto as = lro_admission_->snapshot();
                    fairw = as.fair_window;
                    auto pick = [&](const char* k){ auto it = as.capacities.find(k); return it==as.capacities.end()? 0: it->second; };
                    s_open = pick("open_rtsp"); s_load = pick("load_model"); s_start = pick("start_pipeline");
                }
                if (s_open <= 0) s_open = 1; if (s_load <= 0) s_load = 1; if (s_start <= 0) s_start = 1;
                mb.header("va_subscriptions_slots", "gauge", "Slots for phases");
                auto emit_slot = [&](const char* t, int v){ std::ostringstream ls; ls<<"{type=\""<<t<<"\"}"; mb.sample("va_subscriptions_slots", ls.str(), static_cast<uint64_t>(v)); };
                emit_slot("open_rtsp", s_open);
                emit_slot("load_model", s_load);
                emit_slot("start_pipeline", s_start);
                if (fairw > 0) { mb.header("va_subscriptions_fair_window", "gauge", "Admission fairness window size"); mb.sample("va_subscriptions_fair_window", "{}", static_cast<uint64_t>(fairw)); }
                int slots = std::max(1, std::min({s_open, s_load, s_start}));
                int est = 1; if (ms.queue_length > 0) { double wait = static_cast<double>(ms.queue_length) / static_cast<double>(slots); est = std::max(est, static_cast<int>(std::ceil(wait))); }
                if (est < 1) est = 1; if (est > 60) est = 60;
                mb.header("va_backpressure_retry_after_seconds", "gauge", "Estimated Retry-After based on queue/slots");
                mb.sample("va_backpressure_retry_after_seconds", "{}", static_cast<uint64_t>(est));
            } catch (...) {}
            // Completed totals
            mb.header("va_subscriptions_completed_total", "counter", "Completed subscriptions by result");
            auto c0 = [&](const char* res, unsigned long long v) { std::ostringstream ls; ls<<"{result=\""<<res<<"\"}"; mb.sample("va_subscriptions_completed_total", ls.str(), static_cast<uint64_t>(v)); };
            // Failed by reason (from store snapshot)
            try {
                std::map<std::string, std::uint64_t> fail_by_reason;
                if (lro_store_) {
                    lro_store_->for_each([&](const std::shared_ptr<lro::Operation>& op){
                        if (!op) return; auto st = op->status.load(std::memory_order_relaxed);
                        if (st != lro::Status::Failed) return;
                        std::string r = op->reason.empty()? std::string("unknown"): op->reason;
                        fail_by_reason[r] += 1ULL;
                    });
                }
                if (!fail_by_reason.empty()) {
                    mb.header("va_subscriptions_failed_by_reason_total", "counter", "Failed subscriptions by reason");
                    for (const auto& kv : fail_by_reason) {
                        std::ostringstream ls; ls<<"{reason=\""<<kv.first<<"\"}"; mb.sample("va_subscriptions_failed_by_reason_total", ls.str(), static_cast<uint64_t>(kv.second));
                    }
                }
            } catch (...) {}
            // Completed totals
            mb.header("va_subscriptions_completed_total", "counter", "Completed subscriptions by result");
            // reuse the sampler defined above (avoid duplicate lambda declaration)
            // c0 already defined earlier in this scope
            c0("ready",     ms.completed_ready);
            c0("failed",    ms.completed_failed);
            c0("cancelled", ms.completed_cancelled);
            // Duration histogram (created_at -> terminal finished_at)
            try {
                const double bounds[6] = {0.5,1.0,2.0,5.0,10.0,30.0};
                unsigned long long buckets[6] = {0,0,0,0,0,0};
                unsigned long long total_count = 0ULL; double total_sum = 0.0;
                if (lro_store_) {
                    lro_store_->for_each([&](const std::shared_ptr<lro::Operation>& op){
                        if (!op) return; auto st = op->status.load(std::memory_order_relaxed);
                        if (!(st==lro::Status::Ready || st==lro::Status::Failed || st==lro::Status::Cancelled)) return;
                        if (op->finished_at.time_since_epoch().count() <= 0) return;
                        double sec = std::chrono::duration<double>(op->finished_at - op->created_at).count(); if (sec < 0) sec = 0;
                        size_t bi = 0; while (bi < 6 && sec > bounds[bi]) ++bi; if (bi < 6) buckets[bi]++;
                        total_count++; total_sum += sec;
                    });
                }
                mb.header("va_subscription_duration_seconds", "histogram", "Subscription total duration in seconds");
                unsigned long long acc0 = 0ULL;
                for (int i=0;i<6;++i) { acc0 += buckets[i]; std::ostringstream ls; ls<<"{le=\""<<bounds[i]<<"\"}"; mb.sample("va_subscription_duration_seconds_bucket", ls.str(), static_cast<uint64_t>(acc0)); }
                std::ostringstream lsi0; lsi0 << "{le=\"+Inf\"}"; mb.sample("va_subscription_duration_seconds_bucket", lsi0.str(), static_cast<uint64_t>(total_count));
                mb.sample("va_subscription_duration_seconds_sum", "{}", total_sum);
                mb.sample("va_subscription_duration_seconds_count", "{}", static_cast<uint64_t>(total_count));
            } catch (...) {}
            // States gauges
            mb.header("va_subscriptions_states", "gauge", "Subscriptions by current phase");
            auto g = [&](const char* phase, uint64_t v) { std::ostringstream ls; ls<<"{phase=\""<<phase<<"\"}"; mb.sample("va_subscriptions_states", ls.str(), v); };
            auto get = [&](const char* k){ auto it = ms.states.find(k); return it==ms.states.end()? 0ULL : it->second; };
            g("pending", get("pending")); g("preparing", get("preparing")); g("opening_rtsp", get("opening_rtsp"));
            g("loading_model", get("loading_model")); g("starting_pipeline", get("starting_pipeline")); g("ready", get("ready"));
            g("failed", get("failed")); g("cancelled", get("cancelled"));
        }
        // SSE connection metrics (always)
        try {
            mb.header("va_sse_connections", "gauge", "Active SSE connections by channel");
            auto emit_conn = [&](const char* ch, unsigned long long v){ std::ostringstream ls; ls<<"{channel=\""<<ch<<"\"}"; mb.sample("va_sse_connections", ls.str(), static_cast<uint64_t>(v)); };
            emit_conn("subscriptions", static_cast<unsigned long long>(va::server::g_sse_subscriptions_active.load()));
            emit_conn("sources",       static_cast<unsigned long long>(va::server::g_sse_sources_active.load()));
            emit_conn("logs",          static_cast<unsigned long long>(va::server::g_sse_logs_active.load()));
            emit_conn("events",        static_cast<unsigned long long>(va::server::g_sse_events_active.load()));
            mb.header("va_sse_reconnects_total", "counter", "SSE reconnect events (Last-Event-ID seen)");
            mb.sample("va_sse_reconnects_total", "{}", static_cast<uint64_t>(va::server::g_sse_reconnects_total.load()));
        } catch (...) {}
        // Merge/fairness placeholders (zeros) to keep metric presence
        mb.header("va_subscriptions_merge_total", "counter", "use_existing merge counters by type");
        auto emit_merge0 = [&](const char* t){ std::ostringstream ls; ls<<"{type=\""<<t<<"\"}"; mb.sample("va_subscriptions_merge_total", ls.str(), static_cast<uint64_t>(0ULL)); };
        emit_merge0("non_terminal"); emit_merge0("ready"); emit_merge0("miss");
        mb.header("va_subscriptions_rr_rotations_total", "counter", "Fair scheduling rotations (window picks)");
        mb.sample("va_subscriptions_rr_rotations_total", "{}", static_cast<uint64_t>(0ULL));

        // Quotas: dropped + would-drop + feature toggles (low cardinality)
        try {
            // dropped
            mb.header("va_quota_dropped_total", "counter", "Quota/ACL dropped requests by reason");
            auto emit_drop = [&](const char* reason, unsigned long long val){ std::ostringstream ls; ls<<"{reason=\""<<reason<<"\"}"; mb.sample("va_quota_dropped_total", ls.str(), static_cast<uint64_t>(val)); };
            emit_drop("global_concurrent", quota_drop_global_concurrent_.load(std::memory_order_relaxed));
            emit_drop("key_concurrent",    quota_drop_key_concurrent_.load(std::memory_order_relaxed));
            emit_drop("key_rate",          quota_drop_key_rate_.load(std::memory_order_relaxed));
            emit_drop("acl_scheme",        quota_drop_acl_scheme_.load(std::memory_order_relaxed));
            emit_drop("acl_profile",       quota_drop_acl_profile_.load(std::memory_order_relaxed));

            // would-drop (observe-only path)
            mb.header("va_quota_would_drop_total", "counter", "Quota/ACL would-drop (observe-only) by reason");
            auto emit_would = [&](const char* reason, unsigned long long val){ std::ostringstream ls; ls<<"{reason=\""<<reason<<"\"}"; mb.sample("va_quota_would_drop_total", ls.str(), static_cast<uint64_t>(val)); };
            emit_would("global_concurrent", quota_would_drop_global_concurrent_.load(std::memory_order_relaxed));
            emit_would("key_concurrent",    quota_would_drop_key_concurrent_.load(std::memory_order_relaxed));
            emit_would("key_rate",          quota_would_drop_key_rate_.load(std::memory_order_relaxed));
            emit_would("acl_scheme",        quota_would_drop_acl_scheme_.load(std::memory_order_relaxed));
            emit_would("acl_profile",       quota_would_drop_acl_profile_.load(std::memory_order_relaxed));

            // feature toggles + enforce percent
            mb.header("va_feature_enabled", "gauge", "Feature toggle enabled (1/0)");
            mb.sample("va_feature_enabled", "{feature=\"quota_observe\"}", static_cast<uint64_t>(app.appConfig().quotas.observe_only ? 1 : 0));
            mb.sample("va_feature_enabled", "{feature=\"quota_enforce\"}", static_cast<uint64_t>(app.appConfig().quotas.observe_only ? 0 : 1));
            mb.header("va_quota_enforce_percent", "gauge", "Quota enforce percent (0-100)");
            mb.sample("va_quota_enforce_percent", "{}", static_cast<uint64_t>(app.appConfig().quotas.enforce_percent));
        } catch (...) {}

        HttpResponse resp;
        resp.status_code = 200;
        resp.headers["Content-Type"] = "text/plain; version=0.0.4; charset=utf-8";
        resp.body = mb.str();
        return resp;
    }

    std::ostringstream out;
    // WAL plain-text metrics (best-effort)
    try {
        out << "# HELP va_wal_failed_restart_total Subscriptions inflight before last restart (from WAL)\n";
        out << "# TYPE va_wal_failed_restart_total counter\n";
        out << "va_wal_failed_restart_total {} " << static_cast<unsigned long long>(va::core::wal::failedRestartCount()) << "\n";
        out << "# HELP va_feature_enabled Feature toggle enabled (1/0)\n";
        out << "# TYPE va_feature_enabled gauge\n";
        out << "va_feature_enabled{feature=\"wal\"} " << static_cast<unsigned long long>(va::core::wal::enabled() ? 1 : 0) << "\n";
        // Tail derived event counters (best-effort)
        unsigned long long c_enqueue=0, c_ready=0, c_failed=0, c_cancelled=0, c_restart=0;
        try {
            auto lines = va::core::wal::tail(200);
            for (const auto& s : lines) {
                if (s.find("\"op\":\"enqueue\"") != std::string::npos) c_enqueue++;
                else if (s.find("\"op\":\"ready\"") != std::string::npos) c_ready++;
                else if (s.find("\"op\":\"failed\"") != std::string::npos) c_failed++;
                else if (s.find("\"op\":\"cancelled\"") != std::string::npos) c_cancelled++;
                else if (s.find("\"op\":\"restart\"") != std::string::npos) c_restart++;
            }
        } catch (...) {}
        out << "# HELP va_wal_events_total WAL events observed from tail (best-effort)\n";
        out << "# TYPE va_wal_events_total counter\n";
        out << "va_wal_events_total{op=\"enqueue\"} " << c_enqueue << "\n";
        out << "va_wal_events_total{op=\"ready\"} " << c_ready << "\n";
        out << "va_wal_events_total{op=\"failed\"} " << c_failed << "\n";
        out << "va_wal_events_total{op=\"cancelled\"} " << c_cancelled << "\n";
        out << "va_wal_events_total{op=\"restart\"} " << c_restart << "\n";
    } catch (...) {}
    out << "# HELP va_pipelines_total Total pipelines\n";
    out << "# TYPE va_pipelines_total gauge\n";
    out << "va_pipelines_total " << sys.total_pipelines << "\n";

    out << "# HELP va_pipelines_running Running pipelines\n";
    out << "# TYPE va_pipelines_running gauge\n";
    out << "va_pipelines_running " << sys.running_pipelines << "\n";

    out << "# HELP va_pipeline_aggregate_fps Aggregate FPS across pipelines\n";
    out << "# TYPE va_pipeline_aggregate_fps gauge\n";
    out << "va_pipeline_aggregate_fps " << sys.aggregate_fps << "\n";

    out << "# HELP va_frames_processed_total Frames processed (sum)\n";
    out << "# TYPE va_frames_processed_total counter\n";
    out << "va_frames_processed_total " << sys.processed_frames << "\n";

    out << "# HELP va_frames_dropped_total Frames dropped (sum)\n";
    out << "# TYPE va_frames_dropped_total counter\n";
    out << "va_frames_dropped_total " << sys.dropped_frames << "\n";

    out << "# HELP va_transport_packets_total Transport packets sent (sum)\n";
    out << "# TYPE va_transport_packets_total counter\n";
    out << "va_transport_packets_total " << sys.transport_packets << "\n";

    out << "# HELP va_transport_bytes_total Transport bytes sent (sum)\n";
    out << "# TYPE va_transport_bytes_total counter\n";
    out << "va_transport_bytes_total " << sys.transport_bytes << "\n";

    out << "# HELP va_d2d_nv12_frames_total NVENC device NV12 direct-feed frames\n";
    out << "# TYPE va_d2d_nv12_frames_total counter\n";
    out << "va_d2d_nv12_frames_total " << gm.d2d_nv12_frames << "\n";

    out << "# HELP va_cpu_fallback_skips_total CPU upload skipped (device NV12 path)\n";
    out << "# TYPE va_cpu_fallback_skips_total counter\n";
    out << "va_cpu_fallback_skips_total " << gm.cpu_fallback_skips << "\n";

    out << "# HELP va_encoder_eagain_retry_total Encoder EAGAIN drain+retry occurrences\n";
    out << "# TYPE va_encoder_eagain_retry_total counter\n";
    out << "va_encoder_eagain_retry_total " << gm.eagain_retry_count << "\n";

    out << "# HELP va_overlay_nv12_kernel_hits_total NV12 kernel overlay executions\n";
    out << "# TYPE va_overlay_nv12_kernel_hits_total counter\n";
    out << "va_overlay_nv12_kernel_hits_total " << gm.overlay_nv12_kernel_hits << "\n";

    out << "# HELP va_overlay_nv12_passthrough_total NV12 overlay passthrough (no boxes)\n";
    out << "# TYPE va_overlay_nv12_passthrough_total counter\n";
    out << "va_overlay_nv12_passthrough_total " << gm.overlay_nv12_passthrough << "\n";

    // Control-plane metrics (plain text branch)
    out << "# HELP va_cp_auto_subscribe_total Auto subscribe events (success)\n";
    out << "# TYPE va_cp_auto_subscribe_total counter\n";
    out << "va_cp_auto_subscribe_total " << gm.cp_auto_subscribe_total << "\n";

    out << "# HELP va_cp_auto_unsubscribe_total Auto unsubscribe events (success)\n";
    out << "# TYPE va_cp_auto_unsubscribe_total counter\n";
    out << "va_cp_auto_unsubscribe_total " << gm.cp_auto_unsubscribe_total << "\n";

    out << "# HELP va_cp_auto_switch_source_total Auto source switch events (success)\n";
    out << "# TYPE va_cp_auto_switch_source_total counter\n";
    out << "va_cp_auto_switch_source_total " << gm.cp_auto_switch_source_total << "\n";

    out << "# HELP va_cp_auto_switch_model_total Auto model switch events (success)\n";
    out << "# TYPE va_cp_auto_switch_model_total counter\n";
    out << "va_cp_auto_switch_model_total " << gm.cp_auto_switch_model_total << "\n";

    out << "# HELP va_cp_auto_subscribe_failed_total Auto subscribe failures\n";
    out << "# TYPE va_cp_auto_subscribe_failed_total counter\n";
    out << "va_cp_auto_subscribe_failed_total " << gm.cp_auto_subscribe_failed_total << "\n";

    out << "# HELP va_cp_auto_switch_source_failed_total Auto source switch failures\n";
    out << "# TYPE va_cp_auto_switch_source_failed_total counter\n";
    out << "va_cp_auto_switch_source_failed_total " << gm.cp_auto_switch_source_failed_total << "\n";

    out << "# HELP va_cp_auto_switch_model_failed_total Auto model switch failures\n";
    out << "# TYPE va_cp_auto_switch_model_failed_total counter\n";
    out << "va_cp_auto_switch_model_failed_total " << gm.cp_auto_switch_model_failed_total << "\n";

    // Subscription metrics (plain text)
    if (lro_enabled_ && lro_runner_) {
        auto ms = lro_runner_->metricsSnapshot();
        out << "# HELP va_subscriptions_queue_length Pending subscription tasks in queue\n";
        out << "# TYPE va_subscriptions_queue_length gauge\n";
        out << "va_subscriptions_queue_length " << static_cast<unsigned long long>(ms.queue_length) << "\n";
        // Backpressure (plain text)
        try {
            int s_open = 1, s_load = 1, s_start= 1; int fairw = 0;
            if (lro_admission_) { auto as = lro_admission_->snapshot(); fairw = as.fair_window; auto pick = [&](const char* k){ auto it=as.capacities.find(k); return it==as.capacities.end()? 1: it->second; }; s_open=pick("open_rtsp"); s_load=pick("load_model"); s_start=pick("start_pipeline"); }
            out << "# HELP va_subscriptions_slots Slots for phases\n";
            out << "# TYPE va_subscriptions_slots gauge\n";
            out << "va_subscriptions_slots{type=\"open_rtsp\"} " << s_open  << "\n";
            out << "va_subscriptions_slots{type=\"load_model\"} " << s_load  << "\n";
            out << "va_subscriptions_slots{type=\"start_pipeline\"} " << s_start << "\n";
            if (fairw > 0) {
                out << "# HELP va_subscriptions_fair_window Admission fairness window size\n";
                out << "# TYPE va_subscriptions_fair_window gauge\n";
                out << "va_subscriptions_fair_window " << fairw << "\n";
            }
            int slots = std::max(1, std::min({s_open, s_load, s_start}));
            int est = 1; if (ms.queue_length > 0) { double wait = static_cast<double>(ms.queue_length) / static_cast<double>(slots); est = std::max(est, static_cast<int>(std::ceil(wait))); }
            if (est < 1) est = 1; if (est > 60) est = 60;
            out << "# HELP va_backpressure_retry_after_seconds Estimated Retry-After based on queue/slots\n";
            out << "# TYPE va_backpressure_retry_after_seconds gauge\n";
            out << "va_backpressure_retry_after_seconds " << est << "\n";
        } catch (...) {}
        out << "# HELP va_subscriptions_in_progress Non-terminal subscriptions in progress\n";
        out << "# TYPE va_subscriptions_in_progress gauge\n";
        out << "va_subscriptions_in_progress " << static_cast<unsigned long long>(ms.in_progress) << "\n";
        // Completed totals
        out << "# HELP va_subscriptions_completed_total Completed subscriptions by result\n";
        out << "# TYPE va_subscriptions_completed_total counter\n";
        out << "va_subscriptions_completed_total{result=\"ready\"} " << ms.completed_ready << "\n";
        out << "va_subscriptions_completed_total{result=\"failed\"} " << ms.completed_failed << "\n";
        out << "va_subscriptions_completed_total{result=\"cancelled\"} " << ms.completed_cancelled << "\n";
        // Failed by reason
        try {
            std::map<std::string, std::uint64_t> fail_by_reason;
            if (lro_store_) {
                lro_store_->for_each([&](const std::shared_ptr<lro::Operation>& op){
                    if (!op) return; auto st = op->status.load(std::memory_order_relaxed);
                    if (st != lro::Status::Failed) return;
                    std::string r = op->reason.empty()? std::string("unknown"): op->reason;
                    fail_by_reason[r] += 1ULL;
                });
            }
            if (!fail_by_reason.empty()) {
                out << "# HELP va_subscriptions_failed_by_reason_total Failed subscriptions by reason\n";
                out << "# TYPE va_subscriptions_failed_by_reason_total counter\n";
                for (const auto& kv : fail_by_reason) {
                    out << "va_subscriptions_failed_by_reason_total{reason=\"" << kv.first << "\"} " << kv.second << "\n";
                }
            }
        } catch (...) {}
        // SSE metrics (plain text)
        out << "# HELP va_sse_connections Active SSE connections by channel\n";
        out << "# TYPE va_sse_connections gauge\n";
        out << "va_sse_connections{channel=\"subscriptions\"} " << va::server::g_sse_subscriptions_active.load() << "\n";
        out << "va_sse_connections{channel=\"sources\"} " << va::server::g_sse_sources_active.load() << "\n";
        out << "va_sse_connections{channel=\"logs\"} " << va::server::g_sse_logs_active.load() << "\n";
        out << "va_sse_connections{channel=\"events\"} " << va::server::g_sse_events_active.load() << "\n";
        out << "# HELP va_sse_reconnects_total SSE reconnect events (Last-Event-ID seen)\n";
        out << "# TYPE va_sse_reconnects_total counter\n";
        out << "va_sse_reconnects_total " << va::server::g_sse_reconnects_total.load() << "\n";
        // Merge and fairness metrics
        out << "# HELP va_subscriptions_merge_total use_existing merge counters by type\n";
        out << "# TYPE va_subscriptions_merge_total counter\n";
        out << "va_subscriptions_merge_total{type=\"non_terminal\"} " << 0 << "\n";
        out << "va_subscriptions_merge_total{type=\"ready\"} " << 0 << "\n";
        out << "va_subscriptions_merge_total{type=\"miss\"} " << 0 << "\n";
        out << "# HELP va_subscriptions_rr_rotations_total Fair scheduling rotations (window picks)\n";
        out << "# TYPE va_subscriptions_rr_rotations_total counter\n";
        out << "va_subscriptions_rr_rotations_total " << 0 << "\n";
        out << "# HELP va_subscriptions_states Subscriptions by current phase\n";
        out << "# TYPE va_subscriptions_states gauge\n";
        auto gg = [&](const char* phase, uint64_t v) { out << "va_subscriptions_states{phase=\""<<phase<<"\"} " << v << "\n"; };
        auto get = [&](const char* k){ auto it = ms.states.find(k); return it==ms.states.end()? 0ULL : it->second; };
        gg("pending", get("pending")); gg("preparing", get("preparing")); gg("opening_rtsp", get("opening_rtsp"));
        gg("loading_model", get("loading_model")); gg("starting_pipeline", get("starting_pipeline")); gg("ready", get("ready"));
        gg("failed", get("failed")); gg("cancelled", get("cancelled"));
        // 注意：最小实现暂不输出 completed/histogram；保留基本队列、槽位、在途与状态分布
    }

    // Per-source metrics (labels: source_id, path)
    auto classify_path = [](const va::core::TrackManager::PipelineInfo& info) -> std::string {
        if (info.zc.d2d_nv12_frames > 0) return "d2d";
        std::string lower = info.encoder_cfg.codec;
        std::transform(lower.begin(), lower.end(), lower.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        if (lower.find("nvenc") != std::string::npos) return "gpu";
        return "cpu";
    };

    const bool ext_labels = app.appConfig().observability.metrics_extended_labels;
    // Helper to build label string with optional extended labels
    auto make_labels = [&](const std::string& source_id,
                           const std::string& path,
                           const va::core::TrackManager::PipelineInfo* pinfo) -> std::string {
        std::ostringstream oss;
        oss << "{source_id=\"" << source_id << "\",path=\"" << path << "\"";
        if (ext_labels && pinfo) {
            // decoder label
            if (!pinfo->decoder_label.empty()) {
                oss << ",decoder=\"" << pinfo->decoder_label << "\"";
            }
            // encoder label (codec family)
            if (!pinfo->encoder_cfg.codec.empty()) {
                oss << ",encoder=\"" << pinfo->encoder_cfg.codec << "\"";
            }
            // preproc: derive from engine options (global hint)
            std::string preproc = "cpu";
            auto eng = app.currentEngine();
            auto it = eng.options.find("use_cuda_preproc");
            if (it != eng.options.end()) {
                std::string v = toLower(it->second);
                if (v=="1"||v=="true"||v=="yes"||v=="on") preproc = "cuda";
            }
            oss << ",preproc=\"" << preproc << "\"";
        }
        oss << "}";
        return oss.str();
    };

    // Per-pipeline FPS gauge
    out << "# HELP va_pipeline_fps Pipeline FPS per source\n";
    out << "# TYPE va_pipeline_fps gauge\n";
    for (const auto& info : app.pipelines()) {
        const std::string path = classify_path(info);
        out << "va_pipeline_fps" << make_labels(info.stream_id, path, &info) << " " << info.metrics.fps << "\n";
    }

    // Per-pipeline frames processed/dropped with labels
    for (const auto& info : app.pipelines()) {
        const std::string path = classify_path(info);
        out << "va_frames_processed_total" << make_labels(info.stream_id, path, &info)
            << " " << static_cast<unsigned long long>(info.metrics.processed_frames) << "\n";
        out << "va_frames_dropped_total" << make_labels(info.stream_id, path, &info)
            << " " << static_cast<unsigned long long>(info.metrics.dropped_frames) << "\n";
    }

    // Per-stage latency histograms per source
    const double bounds_ms[10] = {1,2,5,10,20,50,100,200,500,1000};
    out << "# HELP va_frame_latency_ms Frame processing latency per stage\n";
    out << "# TYPE va_frame_latency_ms histogram\n";
    auto emit_hist = [&](const std::string& stage,
                         const std::string& source_id,
                         const std::string& path,
                         const va::core::Pipeline::LatencySnapshot& snap) {
        uint64_t cumulative = 0;
        for (int i=0;i<va::core::Pipeline::LatencySnapshot::kNumBuckets; ++i) {
            cumulative += snap.buckets[i];
            out << "va_frame_latency_ms_bucket{stage=\"" << stage
                << "\",source_id=\"" << source_id
                << "\",path=\"" << path
                << "\",le=\"" << bounds_ms[i] << "\"} "
                << static_cast<unsigned long long>(cumulative) << "\n";
        }
        // +Inf bucket equals total count
        out << "va_frame_latency_ms_bucket{stage=\"" << stage
            << "\",source_id=\"" << source_id
            << "\",path=\"" << path
            << "\",le=\"+Inf\"} "
            << static_cast<unsigned long long>(snap.count) << "\n";
        // sum (ms) and count
        double sum_ms = static_cast<double>(snap.sum_us) / 1000.0;
        out << "va_frame_latency_ms_sum{stage=\"" << stage
            << "\",source_id=\"" << source_id
            << "\",path=\"" << path << "\"} " << sum_ms << "\n";
        out << "va_frame_latency_ms_count{stage=\"" << stage
            << "\",source_id=\"" << source_id
            << "\",path=\"" << path << "\"} "
            << static_cast<unsigned long long>(snap.count) << "\n";
    };
    for (const auto& info : app.pipelines()) {
        const std::string path = classify_path(info);
        emit_hist("preproc", info.stream_id, path, info.stage_latency.preproc);
        emit_hist("infer",   info.stream_id, path, info.stage_latency.infer);
        emit_hist("postproc",info.stream_id, path, info.stage_latency.postproc);
        emit_hist("encode",  info.stream_id, path, info.stage_latency.encode);
    }

    // Frames dropped by reason (per-source)
    {
        auto rows = va::core::DropMetrics::snapshot();
        out << "# HELP va_frames_dropped_total Frames dropped by reason\n";
        out << "# TYPE va_frames_dropped_total counter\n";
        for (const auto& row : rows) {
            auto emit = [&](const char* reason, uint64_t val) {
                if (val == 0) return; // reduce noise
                out << "va_frames_dropped_total{source_id=\"" << row.source_id
                    << "\",reason=\"" << reason << "\"} "
                    << static_cast<unsigned long long>(val) << "\n";
            };
            emit("queue_overflow", row.counters.queue_overflow);
            emit("decode_error",   row.counters.decode_error);
            emit("encode_eagain",  row.counters.encode_eagain);
            emit("backpressure",   row.counters.backpressure);
        }
    }

    // RTSP source reconnects per source
    {
        auto rows = va::core::SourceReconnects::snapshot();
        out << "# HELP va_rtsp_source_reconnects_total RTSP source reconnects\n";
        out << "# TYPE va_rtsp_source_reconnects_total counter\n";
        for (const auto& row : rows) {
            out << "va_rtsp_source_reconnects_total{source_id=\"" << row.source_id << "\"} "
                << static_cast<unsigned long long>(row.reconnects) << "\n";
        }
    }

    // NVDEC device-path recovery and await-IDR events per source
    {
        auto rows = va::core::NvdecEvents::snapshot();
        out << "# HELP va_nvdec_device_recover_total NVDEC device-path recovery events\n";
        out << "# TYPE va_nvdec_device_recover_total counter\n";
        for (const auto& row : rows) {
            out << "va_nvdec_device_recover_total{source_id=\"" << row.source_id << "\"} "
                << static_cast<unsigned long long>(row.device_recover) << "\n";
        }
        out << "# HELP va_nvdec_await_idr_total NVDEC await-IDR occurrences (startup/reopen)\n";
        out << "# TYPE va_nvdec_await_idr_total counter\n";
        for (const auto& row : rows) {
            out << "va_nvdec_await_idr_total{source_id=\"" << row.source_id << "\"} "
                << static_cast<unsigned long long>(row.await_idr) << "\n";
        }
    }

    // Encoder metrics per source (use transport stats as proxy for encoded output)
    out << "# HELP va_encoder_packets_total Encoded packets per source\n";
    out << "# TYPE va_encoder_packets_total counter\n";
    out << "# HELP va_encoder_bytes_total Encoded bytes per source\n";
    out << "# TYPE va_encoder_bytes_total counter\n";
    out << "# HELP va_encoder_eagain_total Encoder EAGAIN occurrences per source\n";
    out << "# TYPE va_encoder_eagain_total counter\n";
    for (const auto& info : app.pipelines()) {
        const std::string path = classify_path(info);
        const std::string codec = info.encoder_cfg.codec;
        std::string base = make_labels(info.stream_id, path, &info);
        // prepend codec label
        auto with_codec = [&](const char* metric) {
            std::ostringstream oss; oss << metric << "{source_id=\"" << info.stream_id << "\"";
            oss << ",path=\"" << path << "\"";
            if (ext_labels && !info.encoder_cfg.codec.empty()) oss << ",encoder=\"" << codec << "\"";
            if (ext_labels && !info.decoder_label.empty()) oss << ",decoder=\"" << info.decoder_label << "\"";
            // preproc
            if (ext_labels) {
                std::string preproc = "cpu";
                auto eng = app.currentEngine();
                auto it = eng.options.find("use_cuda_preproc");
                if (it != eng.options.end()) {
                    std::string v = toLower(it->second);
                    if (v=="1"||v=="true"||v=="yes"||v=="on") preproc = "cuda";
                }
                oss << ",preproc=\"" << preproc << "\"";
            }
            oss << "}"; return oss.str(); };

        out << with_codec("va_encoder_packets_total") << " "
            << static_cast<unsigned long long>(info.transport_stats.packets) << "\n";
        out << with_codec("va_encoder_bytes_total") << " "
            << static_cast<unsigned long long>(info.transport_stats.bytes) << "\n";
        out << with_codec("va_encoder_eagain_total") << " "
            << static_cast<unsigned long long>(info.zc.eagain_retry_count) << "\n";
    }

    // Retention metrics
    out << "# HELP va_db_retention_runs_total Retention job runs total\n";
    out << "# TYPE va_db_retention_runs_total counter\n";
    out << "va_db_retention_runs_total " << static_cast<unsigned long long>(retention_runs_total.load(std::memory_order_relaxed)) << "\n";
    out << "# HELP va_db_retention_failures_total Retention job failures total\n";
    out << "# TYPE va_db_retention_failures_total counter\n";
    out << "va_db_retention_failures_total " << static_cast<unsigned long long>(retention_failures_total.load(std::memory_order_relaxed)) << "\n";
    out << "# HELP va_db_retention_last_ms Last retention job duration in ms\n";
    out << "# TYPE va_db_retention_last_ms gauge\n";
    out << "va_db_retention_last_ms " << static_cast<unsigned long long>(retention_last_ms.load(std::memory_order_relaxed)) << "\n";

    // DB pool metrics
    if (db_pool && db_pool->valid()) {
        va::storage::DbPool::Stats st{}; bool ok = db_pool->getStats(&st);
        if (ok) {
            out << "# HELP va_db_pool_max Maximum pool size\n";
            out << "# TYPE va_db_pool_max gauge\n";
            out << "va_db_pool_max " << st.max << "\n";
            out << "# HELP va_db_pool_min Minimum pool size\n";
            out << "# TYPE va_db_pool_min gauge\n";
            out << "va_db_pool_min " << st.min << "\n";
            out << "# HELP va_db_pool_created Connections created by pool\n";
            out << "# TYPE va_db_pool_created gauge\n";
            out << "va_db_pool_created " << static_cast<unsigned long long>(st.created) << "\n";
            out << "# HELP va_db_pool_idle Idle connections\n";
            out << "# TYPE va_db_pool_idle gauge\n";
            out << "va_db_pool_idle " << static_cast<unsigned long long>(st.idle) << "\n";
            out << "# HELP va_db_pool_in_use Connections currently in-use (approx)\n";
            out << "# TYPE va_db_pool_in_use gauge\n";
            unsigned long long in_use = 0ULL;
            if (st.created >= st.idle) in_use = static_cast<unsigned long long>(st.created - st.idle);
            out << "va_db_pool_in_use " << in_use << "\n";
        }
    }

    // Control-plane request metrics (plain text)
    {
        std::lock_guard<std::mutex> lk(cp_mu);
        out << "# HELP va_cp_requests_total Control-plane requests total by op/code\n";
        out << "# TYPE va_cp_requests_total counter\n";
        for (const auto& kv : cp_totals_by_code) {
            const std::string& op = kv.first;
            for (const auto& kv2 : kv.second) {
                out << "va_cp_requests_total{op=\"" << op << "\",code=\"" << kv2.first << "\"} "
                    << static_cast<unsigned long long>(kv2.second) << "\n";
            }
        }
        out << "# HELP va_cp_request_duration_seconds Control-plane request duration (s)\n";
        out << "# TYPE va_cp_request_duration_seconds histogram\n";
        for (const auto& kvh : cp_hist_buckets) {
            const std::string& op = kvh.first;
            double sum = cp_hist_sum.count(op)? cp_hist_sum.at(op) : 0.0;
            unsigned long long cnt = cp_hist_count.count(op)? cp_hist_count.at(op) : 0ULL;
            unsigned long long acc = 0ULL;
            for (size_t i=0;i<cp_bounds.size();++i) {
                acc += kvh.second[i];
                out << "va_cp_request_duration_seconds_bucket{op=\""<<op<<"\",le=\""<<cp_bounds[i]<<"\"} "<< acc << "\n";
            }
            out << "va_cp_request_duration_seconds_bucket{op=\""<<op<<"\",le=\"+Inf\"} "<< cnt << "\n";
            out << "va_cp_request_duration_seconds_sum{op=\""<<op<<"\"} "<< sum << "\n";
            out << "va_cp_request_duration_seconds_count{op=\""<<op<<"\"} "<< cnt << "\n";
        }
        }

        // Quotas dropped/observe-only counters and feature toggles (plain text)
        // M2: ensure always emitted regardless of pipelines
        out << "# HELP va_quota_dropped_total Quota/ACL dropped requests by reason\n";
        out << "# TYPE va_quota_dropped_total counter\n";
        out << "va_quota_dropped_total{reason=\"global_concurrent\"} " << quota_drop_global_concurrent_.load(std::memory_order_relaxed) << "\n";
        out << "va_quota_dropped_total{reason=\"key_concurrent\"} "    << quota_drop_key_concurrent_.load(std::memory_order_relaxed)    << "\n";
        out << "va_quota_dropped_total{reason=\"key_rate\"} "          << quota_drop_key_rate_.load(std::memory_order_relaxed)          << "\n";
        out << "va_quota_dropped_total{reason=\"acl_scheme\"} "        << quota_drop_acl_scheme_.load(std::memory_order_relaxed)        << "\n";
        out << "va_quota_dropped_total{reason=\"acl_profile\"} "       << quota_drop_acl_profile_.load(std::memory_order_relaxed)       << "\n";

        out << "# HELP va_quota_would_drop_total Quota/ACL would-drop (observe-only) by reason\n";
        out << "# TYPE va_quota_would_drop_total counter\n";
        out << "va_quota_would_drop_total{reason=\"global_concurrent\"} " << quota_would_drop_global_concurrent_.load(std::memory_order_relaxed) << "\n";
        out << "va_quota_would_drop_total{reason=\"key_concurrent\"} "    << quota_would_drop_key_concurrent_.load(std::memory_order_relaxed)    << "\n";
        out << "va_quota_would_drop_total{reason=\"key_rate\"} "          << quota_would_drop_key_rate_.load(std::memory_order_relaxed)          << "\n";
        out << "va_quota_would_drop_total{reason=\"acl_scheme\"} "        << quota_would_drop_acl_scheme_.load(std::memory_order_relaxed)        << "\n";
        out << "va_quota_would_drop_total{reason=\"acl_profile\"} "       << quota_would_drop_acl_profile_.load(std::memory_order_relaxed)       << "\n";

        out << "# HELP va_feature_enabled Feature toggle enabled (1/0)\n";
        out << "# TYPE va_feature_enabled gauge\n";
        out << "va_feature_enabled{feature=\"quota_observe\"} " << (app.appConfig().quotas.observe_only ? 1 : 0) << "\n";
        out << "va_feature_enabled{feature=\"quota_enforce\"} " << (app.appConfig().quotas.observe_only ? 0 : 1) << "\n";
        out << "# HELP va_quota_enforce_percent Quota enforce percent (0-100)\n";
        out << "# TYPE va_quota_enforce_percent gauge\n";
        out << "va_quota_enforce_percent{} " << static_cast<unsigned long long>(app.appConfig().quotas.enforce_percent) << "\n";

        // Async DB writer queue lengths
    {
        std::size_t qev = 0, qlg = 0;
        {
            std::lock_guard<std::mutex> lk(dbq_mutex);
            qev = q_events.size();
            qlg = q_logs.size();
        }
        out << "# HELP va_db_writer_queue_events Pending events rows in queue\n";
        out << "# TYPE va_db_writer_queue_events gauge\n";
        out << "va_db_writer_queue_events " << static_cast<unsigned long long>(qev) << "\n";
        out << "# HELP va_db_writer_queue_logs Pending logs rows in queue\n";
        out << "# TYPE va_db_writer_queue_logs gauge\n";
        out << "va_db_writer_queue_logs " << static_cast<unsigned long long>(qlg) << "\n";
    }

    HttpResponse resp;
    resp.status_code = 200;
    resp.headers["Content-Type"] = "text/plain; version=0.0.4; charset=utf-8";
    resp.body = out.str();
    return resp;
}

HttpResponse RestServer::Impl::handleMetricsConfigGet(const HttpRequest& /*req*/) {
    const auto& obs = app.appConfig().observability;
    const bool reg = metrics_registry_enabled_.has_value() ? *metrics_registry_enabled_ : obs.metrics_registry_enabled;
    const bool ext = metrics_extended_labels_.has_value() ? *metrics_extended_labels_ : obs.metrics_extended_labels;
    Json::Value payload = successPayload();
    Json::Value data(Json::objectValue);
    data["registry_enabled"] = reg;
    data["extended_labels"] = ext;
    payload["data"] = data;
    return jsonResponse(payload, 200);
}

HttpResponse RestServer::Impl::handleMetricsConfigSet(const HttpRequest& req) {
    try {
        const Json::Value body = parseJson(req.body);
        if (body.isMember("registry_enabled")) { metrics_registry_enabled_ = body["registry_enabled"].asBool(); }
        if (body.isMember("extended_labels")) { metrics_extended_labels_ = body["extended_labels"].asBool(); }
        return handleMetricsConfigGet(req);
    } catch (const std::exception& ex) {
        return errorResponse(std::string("metrics set failed: ") + ex.what(), 400);
    }
}

} // namespace va::server

