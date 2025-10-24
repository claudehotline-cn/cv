#include "server/rest_impl.hpp"
#include "analyzer/model_registry.hpp"

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
                    mb.sample("va_cp_requests_total", ls.str(), static_cast<unsigned long long>(kv2.second));
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
                    mb.sample("va_cp_request_duration_seconds_bucket", ls.str(), acc);
                }
                // +Inf bucket
                std::ostringstream lsi; lsi << "{op=\""<<op<<"\",le=\"+Inf\"}"; mb.sample("va_cp_request_duration_seconds_bucket", lsi.str(), cnt);
                // _sum and _count
                std::ostringstream lsn; lsn << "{op=\""<<op<<"\"}";
                mb.sample("va_cp_request_duration_seconds_sum", lsn.str(), sum);
                mb.sample("va_cp_request_duration_seconds_count", lsn.str(), cnt);
            }
        }

        // WAL/Restart metrics (M1)
        try {
            mb.header("va_wal_failed_restart_total", "counter", "Subscriptions inflight before last restart (from WAL)");
            mb.sample("va_wal_failed_restart_total", "{}", static_cast<unsigned long long>(va::core::wal::failedRestartCount()));
        } catch (...) {}

        // Model registry preheat metrics (M1)
        try {
            auto& mr = va::analyzer::ModelRegistry::instance();
            auto rs = mr.metricsSnapshot();
            mb.header("va_model_preheat_enabled", "gauge", "Model preheat enabled (1/0)");
            mb.sample("va_model_preheat_enabled", "{}", static_cast<unsigned long long>(rs.enabled ? 1 : 0));
            mb.header("va_model_preheat_concurrency", "gauge", "Model preheat concurrency");
            mb.sample("va_model_preheat_concurrency", "{}", static_cast<unsigned long long>(rs.concurrency));
            mb.header("va_model_preheat_warmed_total", "gauge", "Models warmed (best-effort)");
            mb.sample("va_model_preheat_warmed_total", "{}", static_cast<unsigned long long>(rs.warmed));
            // duration histogram
            mb.header("va_model_preheat_duration_seconds", "histogram", "Per-model preheat duration (s)");
            unsigned long long accp = 0ULL;
            for (size_t i=0;i<rs.bounds.size(); ++i) { accp += (i<rs.bucket_counts.size()? rs.bucket_counts[i] : 0ULL); std::ostringstream ls; ls << "{le=\""<<rs.bounds[i]<<"\"}"; mb.sample("va_model_preheat_duration_seconds_bucket", ls.str(), accp); }
            std::ostringstream lsi; lsi << "{le=\"+Inf\"}"; mb.sample("va_model_preheat_duration_seconds_bucket", lsi.str(), rs.duration_count);
            mb.sample("va_model_preheat_duration_seconds_sum", "{}", rs.duration_sum);
            mb.sample("va_model_preheat_duration_seconds_count", "{}", rs.duration_count);
            mb.header("va_model_preheat_failed_total", "counter", "Model preheat failures");
            mb.sample("va_model_preheat_failed_total", "{}", static_cast<unsigned long long>(rs.failed_total));
        } catch (...) {}

        // Subscription metrics (from SubscriptionManager, registry branch)
        if (subscriptions) {
            auto ms = subscriptions->metricsSnapshot();
            mb.header("va_subscriptions_queue_length", "gauge", "Pending subscription tasks in queue");
            mb.sample("va_subscriptions_queue_length", "{}", static_cast<unsigned long long>(ms.queue_length));
            mb.header("va_subscriptions_in_progress", "gauge", "Non-terminal subscriptions in progress");
            mb.sample("va_subscriptions_in_progress", "{}", static_cast<unsigned long long>(ms.in_progress));
            // States gauges
            mb.header("va_subscriptions_states", "gauge", "Subscriptions by current phase");
            auto g = [&](const char* phase, uint64_t v) { std::ostringstream ls; ls<<"{phase=\""<<phase<<"\"}"; mb.sample("va_subscriptions_states", ls.str(), v); };
            g("pending", ms.pending); g("preparing", ms.preparing); g("opening_rtsp", ms.opening);
            g("loading_model", ms.loading); g("starting_pipeline", ms.starting); g("ready", ms.ready);
            g("failed", ms.failed); g("cancelled", ms.cancelled);
            // Completed totals by result
            mb.header("va_subscriptions_completed_total", "counter", "Completed subscriptions by result");
            auto c = [&](const char* res, uint64_t v) { std::ostringstream ls; ls<<"{result=\""<<res<<"\"}"; mb.sample("va_subscriptions_completed_total", ls.str(), v); };
            c("ready", ms.completed_ready_total); c("failed", ms.completed_failed_total); c("cancelled", ms.completed_cancelled_total);
            if (!ms.failed_by_reason.empty()) {
                mb.header("va_subscriptions_failed_by_reason_total", "counter", "Failed subscriptions by reason");
                for (const auto& kv : ms.failed_by_reason) {
                    std::ostringstream ls; ls<<"{reason=\""<<kv.first<<"\"}"; mb.sample("va_subscriptions_failed_by_reason_total", ls.str(), kv.second);
                }
            }
            // Duration histogram
            mb.header("va_subscription_duration_seconds", "histogram", "Subscription total duration in seconds");
            unsigned long long acc = 0ULL;
            for (size_t i=0;i<ms.bounds.size();++i) {
                acc += ms.bucket_counts[i];
                std::ostringstream ls; ls<<"{le=\""<<ms.bounds[i]<<"\"}"; mb.sample("va_subscription_duration_seconds_bucket", ls.str(), acc);
            }
            std::ostringstream lsi; lsi<<"{le=\"+Inf\"}"; mb.sample("va_subscription_duration_seconds_bucket", lsi.str(), ms.duration_count);
            mb.sample("va_subscription_duration_seconds_sum", "{}", ms.duration_sum);
            mb.sample("va_subscription_duration_seconds_count", "{}", ms.duration_count);

            // Per-phase duration histograms
            auto emit_phase = [&](const char* phase,
                                  const std::vector<uint64_t>& buckets,
                                  double sum,
                                  uint64_t cnt) {
                mb.header("va_subscription_phase_seconds", "histogram", "Subscription phase duration in seconds");
                unsigned long long accp = 0ULL;
                for (size_t i=0;i<ms.bounds.size(); ++i) {
                    accp += (i<buckets.size()? buckets[i]:0ULL);
                    std::ostringstream ls; ls << "{phase=\""<<phase<<"\",le=\""<<ms.bounds[i]<<"\"}";
                    mb.sample("va_subscription_phase_seconds_bucket", ls.str(), accp);
                }
                std::ostringstream lsi2; lsi2 << "{phase=\""<<phase<<"\",le=\"+Inf\"}"; mb.sample("va_subscription_phase_seconds_bucket", lsi2.str(), cnt);
                std::ostringstream lss; lss << "{phase=\""<<phase<<"\"}";
                mb.sample("va_subscription_phase_seconds_sum", lss.str(), sum);
                mb.sample("va_subscription_phase_seconds_count", lss.str(), cnt);
            };
            emit_phase("opening_rtsp", ms.opening_bucket_counts, ms.opening_duration_sum, ms.opening_duration_count);
            emit_phase("loading_model", ms.loading_bucket_counts, ms.loading_duration_sum, ms.loading_duration_count);
            emit_phase("starting_pipeline", ms.starting_bucket_counts, ms.starting_duration_sum, ms.starting_duration_count);
        }

        HttpResponse resp;
        resp.status_code = 200;
        resp.headers["Content-Type"] = "text/plain; version=0.0.4; charset=utf-8";
        resp.body = mb.str();
        return resp;
    }

    std::ostringstream out;
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
    if (subscriptions) {
        auto ms = subscriptions->metricsSnapshot();
        out << "# HELP va_subscriptions_queue_length Pending subscription tasks in queue\n";
        out << "# TYPE va_subscriptions_queue_length gauge\n";
        out << "va_subscriptions_queue_length " << static_cast<unsigned long long>(ms.queue_length) << "\n";
        out << "# HELP va_subscriptions_in_progress Non-terminal subscriptions in progress\n";
        out << "# TYPE va_subscriptions_in_progress gauge\n";
        out << "va_subscriptions_in_progress " << static_cast<unsigned long long>(ms.in_progress) << "\n";
        out << "# HELP va_subscriptions_states Subscriptions by current phase\n";
        out << "# TYPE va_subscriptions_states gauge\n";
        auto gg = [&](const char* phase, uint64_t v) { out << "va_subscriptions_states{phase=\""<<phase<<"\"} " << v << "\n"; };
        gg("pending", ms.pending); gg("preparing", ms.preparing); gg("opening_rtsp", ms.opening);
        gg("loading_model", ms.loading); gg("starting_pipeline", ms.starting); gg("ready", ms.ready);
        gg("failed", ms.failed); gg("cancelled", ms.cancelled);
    out << "# HELP va_subscriptions_completed_total Completed subscriptions by result\n";
    out << "# TYPE va_subscriptions_completed_total counter\n";
    out << "va_subscriptions_completed_total{result=\"ready\"} " << ms.completed_ready_total << "\n";
    out << "va_subscriptions_completed_total{result=\"failed\"} " << ms.completed_failed_total << "\n";
    out << "va_subscriptions_completed_total{result=\"cancelled\"} " << ms.completed_cancelled_total << "\n";
    if (!ms.failed_by_reason.empty()) {
        out << "# HELP va_subscriptions_failed_by_reason_total Failed subscriptions by reason\n";
        out << "# TYPE va_subscriptions_failed_by_reason_total counter\n";
        for (const auto& kv : ms.failed_by_reason) {
            out << "va_subscriptions_failed_by_reason_total{reason=\"" << kv.first << "\"} " << kv.second << "\n";
        }
    }
        out << "# HELP va_subscription_duration_seconds Subscription total duration in seconds\n";
        out << "# TYPE va_subscription_duration_seconds histogram\n";
        unsigned long long acc = 0ULL;
        for (size_t i=0;i<ms.bounds.size();++i) { acc += ms.bucket_counts[i]; out << "va_subscription_duration_seconds_bucket{le=\""<<ms.bounds[i]<<"\"} " << acc << "\n"; }
        out << "va_subscription_duration_seconds_bucket{le=\"+Inf\"} " << ms.duration_count << "\n";
        out << "va_subscription_duration_seconds_sum " << ms.duration_sum << "\n";
        out << "va_subscription_duration_seconds_count " << ms.duration_count << "\n";

        // Per-phase histograms (opening_rtsp/loading_model/starting_pipeline)
        auto emit_phase_txt = [&](const char* phase, const std::vector<uint64_t>& buckets, double sum, uint64_t cnt) {
            out << "# HELP va_subscription_phase_seconds Subscription phase duration in seconds\n";
            out << "# TYPE va_subscription_phase_seconds histogram\n";
            unsigned long long accp = 0ULL;
            for (size_t i=0;i<ms.bounds.size(); ++i) { accp += (i<buckets.size()? buckets[i]:0ULL); out << "va_subscription_phase_seconds_bucket{phase=\""<<phase<<"\",le=\""<<ms.bounds[i]<<"\"} " << accp << "\n"; }
            out << "va_subscription_phase_seconds_bucket{phase=\""<<phase<<"\",le=\"+Inf\"} " << cnt << "\n";
            out << "va_subscription_phase_seconds_sum{phase=\""<<phase<<"\"} " << sum << "\n";
            out << "va_subscription_phase_seconds_count{phase=\""<<phase<<"\"} " << cnt << "\n";
        };
        emit_phase_txt("opening_rtsp", ms.opening_bucket_counts, ms.opening_duration_sum, ms.opening_duration_count);
        emit_phase_txt("loading_model", ms.loading_bucket_counts, ms.loading_duration_sum, ms.loading_duration_count);
        emit_phase_txt("starting_pipeline", ms.starting_bucket_counts, ms.starting_duration_sum, ms.starting_duration_count);
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
