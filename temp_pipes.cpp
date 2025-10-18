            data.append(modelToJson(model));
        }
        payload["data"] = data;
        return jsonResponse(payload, 200);
    }

    // Runtime metrics flags overrides (optional)
    std::optional<bool> metrics_registry_enabled_{};
    std::optional<bool> metrics_extended_labels_{};

    HttpResponse handleProfiles(const HttpRequest& /*req*/) {
        Json::Value payload = successPayload();
        Json::Value data(Json::arrayValue);
        for (const auto& profile : app.profiles()) {
            data.append(profileToJson(profile));
        }
        payload["data"] = data;
        return jsonResponse(payload, 200);
    }

      HttpResponse handlePipelines(const HttpRequest& /*req*/) {
        Json::Value payload = successPayload();
        Json::Value data(Json::arrayValue);
        for (const auto& info : app.pipelines()) {
            Json::Value node(Json::objectValue);
            node["key"] = info.key;
            node["stream_id"] = info.stream_id;
            node["profile_id"] = info.profile_id;
            node["source_uri"] = info.source_uri;
            node["model_id"] = info.model_id;
            node["task"] = info.task;
            node["running"] = info.running;
            node["last_active_ms"] = info.last_active_ms;
            node["track_id"] = info.track_id;
            node["metrics"] = metricsToJson(info.metrics);
            // Per-pipeline zero-copy metrics
            {
                Json::Value z(Json::objectValue);
                z["d2d_nv12_frames"] = static_cast<Json::UInt64>(info.zc.d2d_nv12_frames);
                z["cpu_fallback_skips"] = static_cast<Json::UInt64>(info.zc.cpu_fallback_skips);
                z["eagain_retry_count"] = static_cast<Json::UInt64>(info.zc.eagain_retry_count);
                z["overlay_nv12_kernel_hits"] = static_cast<Json::UInt64>(info.zc.overlay_nv12_kernel_hits);
                z["overlay_nv12_passthrough"] = static_cast<Json::UInt64>(info.zc.overlay_nv12_passthrough);
                node["zerocopy_metrics"] = z;
            }
            node["transport_stats"] = transportStatsToJson(info.transport_stats);
            node["encoder"] = encoderConfigToJson(info.encoder_cfg);
            data.append(std::move(node));
        }
        payload["data"] = data;
        return jsonResponse(payload, 200);
    }

