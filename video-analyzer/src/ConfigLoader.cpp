#include "ConfigLoader.hpp"

#include <yaml-cpp/yaml.h>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <fstream>

namespace {

std::string makePath(const std::string& dir, const std::string& name) {
    if (dir.empty()) return name;
    char last = dir.back();
    if (last == '/' || last == '\\') return dir + name;
    return dir + "/" + name;
}

YAML::Node loadYamlFile(const std::string& path) {
    try {
        return YAML::LoadFile(path);
    } catch (const std::exception&) {
        return YAML::Node();
    }
}

size_t parseByteOption(const YAML::Node& node,
                       const char* key_bytes,
                       const char* key_mb,
                       size_t fallback) {
    if (!node || !node.IsMap()) {
        return fallback;
    }

    const auto bytes_node = node[key_bytes];
    if (bytes_node) {
        try {
            auto value = bytes_node.as<long long>(-1);
            if (value >= 0) {
                return static_cast<size_t>(value);
            }
        } catch (...) {
            // ignore parse error, fall back
        }
    }

    const auto mb_node = node[key_mb];
    if (mb_node) {
        try {
            const double mb = mb_node.as<double>(0.0);
            if (mb > 0.0) {
                const auto bytes = static_cast<long long>(std::llround(mb * 1024.0 * 1024.0));
                if (bytes > 0) {
                    return static_cast<size_t>(bytes);
                }
            }
        } catch (...) {
            // ignore parse error, fall back
        }
    }

    return fallback;
}

DetectionModelEntry parseModelVariant(const std::string& task,
                                      const std::string& family,
                                      const std::string& variant,
                                      const YAML::Node& value) {
    DetectionModelEntry entry;
    entry.task = task;
    entry.family = family;
    entry.variant = variant;
    entry.type = value["type"].as<std::string>(value["format"].as<std::string>("onnx"));

    if (!variant.empty()) {
        entry.id = task + ":" + family + ":" + variant;
    } else {
        entry.id = task + ":" + family;
    }

    if (value.IsScalar()) {
        entry.path = value.as<std::string>();
    } else if (value.IsMap()) {
        entry.path = value["onnx"].as<std::string>(value["path"].as<std::string>(""));

        const auto input_size = value["input_size"];
        if (value["input_w"] || value["input_h"] || value["input_width"] || value["input_height"]) {
            entry.input_width = value["input_w"].as<int>(value["input_width"].as<int>(0));
            entry.input_height = value["input_h"].as<int>(value["input_height"].as<int>(0));
        } else if (input_size && input_size.IsSequence() && input_size.size() >= 2) {
            entry.input_width = input_size[0].as<int>();
            entry.input_height = input_size[1].as<int>();
        }

        const auto defaults = value["defaults"];
        if (defaults && defaults.IsMap()) {
            entry.conf = defaults["conf"].as<float>(defaults["confidence_threshold"].as<float>(entry.conf));
            entry.iou = defaults["iou"].as<float>(defaults["nms_threshold"].as<float>(entry.iou));
        }
    }

    if (entry.path.empty()) {
        entry.id.clear();
    }
    return entry;
}

ProfileEntry parseProfileEntry(const std::string& name, const YAML::Node& v) {
    ProfileEntry entry;
    entry.name = name;
    entry.task = v["task"].as<std::string>("det");

    const auto model_node = v["model"];
    if (model_node && model_node.IsMap()) {
        const auto& m = model_node;
        entry.model_id = m["id"].as<std::string>("");
        entry.model_family = m["family"].as<std::string>("");
        entry.model_variant = m["variant"].as<std::string>(m["model"].as<std::string>(""));
        entry.model_path = m["onnx"].as<std::string>(m["path"].as<std::string>(""));
        entry.input_width = m["input_w"].as<int>(m["input_width"].as<int>(0));
        entry.input_height = m["input_h"].as<int>(m["input_height"].as<int>(0));

        if (entry.model_id.empty()) {
            if (!entry.model_family.empty() && !entry.model_variant.empty()) {
                entry.model_id = entry.task + ":" + entry.model_family + ":" + entry.model_variant;
            } else if (!entry.model_path.empty()) {
                entry.model_id = entry.model_path;
            }
        }
    }

    const auto encoder_node = v["encoder"];
    if (encoder_node && encoder_node.IsMap()) {
        const auto& e = encoder_node;
        entry.enc_width = e["w"].as<int>(e["width"].as<int>(0));
        entry.enc_height = e["h"].as<int>(e["height"].as<int>(0));
        entry.enc_fps = e["fps"].as<int>(0);
        entry.enc_bitrate_kbps = e["bitrate_kbps"].as<int>(e["bitrate"].as<int>(0));
        entry.enc_gop = e["gop"].as<int>(0);
        entry.enc_bframes = e["bframes"].as<int>(0);
        entry.enc_zero_latency = e["zero_latency"].as<bool>(true);
        entry.enc_preset = e["preset"].as<std::string>("");
        entry.enc_tune = e["tune"].as<std::string>("");
        entry.enc_profile = e["profile"].as<std::string>("");
        entry.enc_codec = e["codec"].as<std::string>("");
    }

    const auto publish_node = v["publish"];
    if (publish_node && publish_node.IsMap()) {
        const auto& pub = publish_node;
        entry.publish_whip_template = pub["whip_url_template"].as<std::string>("");
        entry.publish_whep_template = pub["whep_url_template"].as<std::string>("");
    }

    return entry;
}

AnalyzerParamsEntry parseAnalyzerParamsEntry(const YAML::Node& v) {
    AnalyzerParamsEntry entry;
    entry.conf = v["conf"].as<float>(v["confidence_threshold"].as<float>(entry.conf));
    entry.iou = v["iou"].as<float>(v["nms_threshold"].as<float>(entry.iou));

    const auto class_whitelist = v["class_whitelist"];
    if (class_whitelist && class_whitelist.IsSequence()) {
        for (const auto& cls : class_whitelist) {
            entry.class_whitelist.emplace_back(cls.as<std::string>());
        }
    }

    if (v["classes"]) {
        if (v["classes"].IsSequence()) {
            for (const auto& cls : v["classes"]) {
                entry.class_whitelist.emplace_back(cls.as<std::string>());
            }
        } else if (v["classes"].IsScalar()) {
            entry.classes_literal = v["classes"].as<std::string>();
        }
    }

    return entry;
}

AppConfigPayload parseAppConfig(const YAML::Node& v) {
    AppConfigPayload payload;
    const auto engine_node = v["engine"];
    if (engine_node && engine_node.IsMap()) {
        const auto& eng = engine_node;
        payload.engine.type = eng["type"].as<std::string>("ort-cpu");
        payload.engine.provider = eng["provider"].as<std::string>(payload.engine.type);
        payload.engine.device = eng["device"].as<int>(0);

        const auto options_node = eng["options"];
        if (options_node && options_node.IsMap()) {
            auto& opts = payload.engine.options;
            opts.use_io_binding = options_node["use_io_binding"].as<bool>(opts.use_io_binding);
            opts.prefer_pinned_memory = options_node["prefer_pinned_memory"].as<bool>(opts.prefer_pinned_memory);
            opts.allow_cpu_fallback = options_node["allow_cpu_fallback"].as<bool>(opts.allow_cpu_fallback);
            opts.enable_profiling = options_node["enable_profiling"].as<bool>(opts.enable_profiling);
            opts.tensorrt_fp16 = options_node["trt_fp16"].as<bool>(opts.tensorrt_fp16);
            opts.tensorrt_int8 = options_node["trt_int8"].as<bool>(opts.tensorrt_int8);
            opts.tensorrt_workspace_mb = options_node["trt_workspace_mb"].as<int>(
                options_node["trt_workspace"].as<int>(opts.tensorrt_workspace_mb));
            opts.tensorrt_max_partition_iterations = options_node["trt_max_partition_iterations"].as<int>(
                opts.tensorrt_max_partition_iterations);
            opts.tensorrt_min_subgraph_size = options_node["trt_min_subgraph_size"].as<int>(
                opts.tensorrt_min_subgraph_size);
            opts.io_binding_input_bytes = parseByteOption(options_node, "io_binding_input_bytes", "io_binding_input_mb", opts.io_binding_input_bytes);
            opts.io_binding_output_bytes = parseByteOption(options_node, "io_binding_output_bytes", "io_binding_output_mb", opts.io_binding_output_bytes);
        }
    }
    const auto sfu_node = v["sfu"];
    if (sfu_node && sfu_node.IsMap()) {
        const auto& sfu = sfu_node;
        payload.sfu_whip_base = sfu["whip_base"].as<std::string>("");
        payload.sfu_whep_base = sfu["whep_base"].as<std::string>("");
    }
    const auto observability_node = v["observability"];
    if (observability_node && observability_node.IsMap()) {
        auto& obs = payload.observability;
        obs.log_level = observability_node["log_level"].as<std::string>(obs.log_level);
        obs.console = observability_node["console"].as<bool>(obs.console);
        obs.log_format = observability_node["log_format"].as<std::string>(obs.log_format);
        // module levels can be a scalar string or a map {comp: level}
        if (observability_node["module_levels"]) {
            const auto ml = observability_node["module_levels"];
            if (ml.IsScalar()) {
                obs.module_levels = ml.as<std::string>(obs.module_levels);
            } else if (ml.IsMap()) {
                // flatten map into "k1:v1,k2:v2"
                std::ostringstream oss;
                bool first = true;
                for (auto it = ml.begin(); it != ml.end(); ++it) {
                    const std::string k = it->first.as<std::string>("");
                    const std::string v = it->second.as<std::string>("");
                    if (k.empty() || v.empty()) continue;
                    if (!first) oss << ","; first = false;
                    oss << k << ":" << v;
                }
                obs.module_levels = oss.str();
            }
        } else if (observability_node["modules"]) {
            const auto ml = observability_node["modules"];
            if (ml.IsMap()) {
                std::ostringstream oss;
                bool first = true;
                for (auto it = ml.begin(); it != ml.end(); ++it) {
                    const std::string k = it->first.as<std::string>("");
                    const std::string v = it->second.as<std::string>("");
                    if (k.empty() || v.empty()) continue;
                    if (!first) oss << ","; first = false;
                    oss << k << ":" << v;
                }
                obs.module_levels = oss.str();
            } else if (ml.IsScalar()) {
                obs.module_levels = ml.as<std::string>(obs.module_levels);
            }
        }

        const auto file_node = observability_node["file"];
        if (file_node) {
            if (file_node.IsMap()) {
                obs.file_path = file_node["path"].as<std::string>(obs.file_path);
                obs.file_max_size_kb = file_node["max_size_kb"].as<int>(obs.file_max_size_kb);
                obs.file_max_files = file_node["max_files"].as<int>(obs.file_max_files);
            } else if (file_node.IsScalar()) {
                obs.file_path = file_node.as<std::string>();
            }
        } else if (observability_node["file_path"]) {
            obs.file_path = observability_node["file_path"].as<std::string>(obs.file_path);
        }

        const auto pipeline_node = observability_node["pipeline_metrics"];
        if (pipeline_node && pipeline_node.IsMap()) {
            obs.pipeline_metrics_enabled = pipeline_node["enabled"].as<bool>(obs.pipeline_metrics_enabled);
            obs.pipeline_metrics_interval_ms = pipeline_node["interval_ms"].as<int>(obs.pipeline_metrics_interval_ms);
        } else {
            if (observability_node["pipeline_metrics_enabled"]) {
                obs.pipeline_metrics_enabled = observability_node["pipeline_metrics_enabled"].as<bool>(obs.pipeline_metrics_enabled);
            }
            if (observability_node["pipeline_metrics_interval_ms"]) {
                obs.pipeline_metrics_interval_ms = observability_node["pipeline_metrics_interval_ms"].as<int>(obs.pipeline_metrics_interval_ms);
            }
        }
    }
    return payload;
}

}

std::vector<DetectionModelEntry> ConfigLoader::loadDetectionModels(const std::string& config_dir) {
    std::vector<DetectionModelEntry> models;
    YAML::Node root = loadYamlFile(makePath(config_dir, "models.yaml"));
    YAML::Node models_node = root["models"] ? root["models"] : root;
    if (!models_node || !models_node.IsMap()) {
        return models;
    }

    for (auto it = models_node.begin(); it != models_node.end(); ++it) {
        const std::string task_name = it->first.as<std::string>();
        const YAML::Node& families = it->second;
        if (!families.IsMap()) {
            continue;
        }

        for (auto fit = families.begin(); fit != families.end(); ++fit) {
            const std::string family_name = fit->first.as<std::string>();
            const YAML::Node& variants = fit->second;

            if (variants.IsMap()) {
                for (auto vit = variants.begin(); vit != variants.end(); ++vit) {
                    const std::string variant_name = vit->first.as<std::string>();
                    DetectionModelEntry entry = parseModelVariant(task_name, family_name, variant_name, vit->second);
                    if (!entry.id.empty()) {
                        models.emplace_back(std::move(entry));
                    }
                }
            } else if (variants.IsScalar()) {
                DetectionModelEntry entry = parseModelVariant(task_name, family_name, "", variants);
                if (!entry.id.empty()) {
                    models.emplace_back(std::move(entry));
                }
            }
        }
    }
    return models;
}

std::vector<ProfileEntry> ConfigLoader::loadProfiles(const std::string& config_dir) {
    std::vector<ProfileEntry> profiles;
    YAML::Node root = loadYamlFile(makePath(config_dir, "profiles.yaml"));
    YAML::Node profiles_node = root["profiles"] ? root["profiles"] : root;
    if (!profiles_node || !profiles_node.IsMap()) {
        return profiles;
    }

    for (auto it = profiles_node.begin(); it != profiles_node.end(); ++it) {
        const std::string name = it->first.as<std::string>();
        profiles.emplace_back(parseProfileEntry(name, it->second));
    }
    return profiles;
}

AppConfigPayload ConfigLoader::loadAppConfig(const std::string& config_dir) {
    YAML::Node root = loadYamlFile(makePath(config_dir, "app.yaml"));
    return parseAppConfig(root);
}

std::map<std::string, AnalyzerParamsEntry> ConfigLoader::loadAnalyzerParams(const std::string& config_dir) {
    std::map<std::string, AnalyzerParamsEntry> params;
    YAML::Node root = loadYamlFile(makePath(config_dir, "analyzer_params.yaml"));
    YAML::Node params_node = root["params"] ? root["params"] : root;
    if (!params_node || !params_node.IsMap()) {
        return params;
    }

    for (auto it = params_node.begin(); it != params_node.end(); ++it) {
        const std::string task_name = it->first.as<std::string>();
        const YAML::Node& task_value = it->second;
        if (!task_value.IsMap()) {
            continue;
        }
        std::string key = task_name;
        std::transform(key.begin(), key.end(), key.begin(), [](unsigned char c){ return static_cast<char>(std::tolower(c)); });
        params.emplace(key, parseAnalyzerParamsEntry(task_value));
    }
    return params;
}


