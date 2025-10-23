#include "server/rest_impl.hpp"

namespace va::server {

    HttpResponse RestServer::Impl::handleCpApply(const HttpRequest& req) {
#if defined(USE_GRPC) && defined(VA_ENABLE_GRPC_SERVER)
        // parse
        Json::Value body(Json::objectValue);
        try { body = parseJson(req.body); }
        catch (const std::exception& ex) { return errorResponse(std::string("parse: ") + ex.what(), 400); }
        // build spec (avoid isMember; prefer operator[] checks)
        va::control::PlainPipelineSpec spec;
        try {
            if (!body.isObject()) return errorResponse("Invalid JSON: object required", 400);
            const auto& jn = body["pipeline_name"]; if (!jn.isString()) return errorResponse("Missing required field: pipeline_name", 400); spec.name = jn.asString();
            const auto& jrev = body["revision"];    if (jrev.isString())      spec.revision  = jrev.asString();
            const auto& jgid = body["graph_id"];    if (jgid.isString())      spec.graph_id  = jgid.asString();
            const auto& jyml = body["yaml_path"];   if (jyml.isString())      spec.yaml_path = jyml.asString();
            const auto& jtpl = body["template_id"]; if (jtpl.isString())      spec.template_id = jtpl.asString();
            const auto& jprj = body["project"];     if (jprj.isString())      spec.project   = jprj.asString();
            const auto& jtags= body["tags"];        if (jtags.isArray())      { for (const auto& t : jtags) if (t.isString()) spec.tags.push_back(t.asString()); }
            const auto& jov  = body["overrides"];   if (jov.isObject())       { for (const auto& k : jov.getMemberNames()) spec.overrides[k] = jov[k].asString(); }
        } catch (const std::exception& ex) { return errorResponse(std::string("validate: ") + ex.what(), 400); }
        // Require at least one of graph_id/yaml_path/template_id
        if (spec.graph_id.empty() && spec.yaml_path.empty() && spec.template_id.empty()) {
            return errorResponse("Missing graph_id/yaml_path/template_id", 400);
        }
        // Build warnings for unknown override keys (best-effort)
        std::vector<std::string> warn_keys;
        try {
            for (const auto& kv : spec.overrides) {
                const std::string& k = kv.first;
                auto has_prefix = [&](const char* p) { return k.rfind(p, 0) == 0; };
                if (has_prefix("engine.") || has_prefix("engine.options.") ||
                    has_prefix("params.") || has_prefix("overrides.params.") ||
                    has_prefix("node.") || k.rfind("type:", 0) == 0) {
                    continue;
                }
                warn_keys.push_back(k);
            }
        } catch (...) { /* ignore warnings build errors */ }
        // controller
        try {
            std::string err;
            bool ok = app.applyPipeline(spec, &err);
            if (!ok) return errorResponse(err.empty()? "apply failed" : err, 409);
            Json::Value payload = successPayload();
            payload["accepted"] = ok;
            if (!warn_keys.empty()) { Json::Value ws(Json::arrayValue); for (const auto& w : warn_keys) ws.append(w); payload["warnings"] = ws; }
            // Record DB event/log (best-effort)
            emitEvent("info", "apply_pipeline", spec.name, "control", std::string(), std::string("apply ") + spec.name);
            emitLog("info", spec.name, "control", std::string(), "apply_pipeline accepted");
            return jsonResponse(payload, 200);
        } catch (const std::exception& ex) { return errorResponse(std::string("apply: ") + ex.what(), 500); }
#else
        return errorResponse("control-plane disabled", 503);
#endif
    }

    HttpResponse RestServer::Impl::handleCpApplyBatch(const HttpRequest& req) {
#if defined(USE_GRPC) && defined(VA_ENABLE_GRPC_SERVER)
        try {
            Json::Value body = parseJson(req.body);
            if (!body.isMember("items") || !body["items"].isArray()) {
                return errorResponse("Missing required array: items", 400);
            }
            std::vector<va::control::PlainPipelineSpec> items;
            for (const auto& it : body["items"]) {
                if (!it.isObject()) continue;
                va::control::PlainPipelineSpec spec;
                if (it.isMember("pipeline_name") && it["pipeline_name"].isString()) spec.name = it["pipeline_name"].asString();
                if (it.isMember("revision") && it["revision"].isString()) spec.revision = it["revision"].asString();
                if (it.isMember("graph_id") && it["graph_id"].isString()) spec.graph_id = it["graph_id"].asString();
                if (it.isMember("yaml_path") && it["yaml_path"].isString()) spec.yaml_path = it["yaml_path"].asString();
                if (it.isMember("template_id") && it["template_id"].isString()) spec.template_id = it["template_id"].asString();
                if (it.isMember("project") && it["project"].isString()) spec.project = it["project"].asString();
                if (it.isMember("tags") && it["tags"].isArray()) {
                    for (const auto& t : it["tags"]) if (t.isString()) spec.tags.push_back(t.asString());
                }
                if (it.isMember("overrides") && it["overrides"].isObject()) {
                    for (const auto& k : it["overrides"].getMemberNames()) spec.overrides[k] = it["overrides"][k].asString();
                }
                items.push_back(std::move(spec));
            }
            std::vector<std::string> errors;
            int accepted = app.applyPipelines(items, &errors);
            Json::Value payload = successPayload();
            payload["accepted"] = accepted;
            Json::Value errs(Json::arrayValue); for (const auto& e : errors) errs.append(e);
            payload["errors"] = errs;
            emitEvent("info", "apply_pipelines", std::string(), "control", std::string(), std::string("accepted=") + std::to_string(accepted));
            emitLog("info", std::string(), "control", std::string(), "apply_pipelines finished");
            return jsonResponse(payload, 200);
        } catch (const std::exception& ex) {
            return errorResponse(std::string("exception: ") + ex.what(), 500);
        }
#else
        return errorResponse("control-plane disabled", 503);
#endif
    }

    HttpResponse RestServer::Impl::handleCpHotSwap(const HttpRequest& req) {
#if defined(USE_GRPC) && defined(VA_ENABLE_GRPC_SERVER)
        // parse
        Json::Value body(Json::objectValue);
        try { body = parseJson(req.body); }
        catch (const std::exception& ex) { return errorResponse(std::string("parse: ") + ex.what(), 400); }
        // validate (avoid isMember; use operator[] nullValue semantics)
        std::string name, node, uri;
        try {
            if (!body.isObject()) return errorResponse("Invalid JSON: object required", 400);
            const auto& jn = body["pipeline_name"]; if (!jn.isString()) return errorResponse("Missing pipeline_name", 400); name = jn.asString();
            const auto& jnode = body["node"]; if (!jnode.isString()) return errorResponse("Missing node", 400); node = jnode.asString();
            const auto& juri = body["model_uri"]; if (!juri.isString()) return errorResponse("Missing model_uri", 400); uri = juri.asString();
        } catch (const std::exception& ex) { return errorResponse(std::string("validate: ") + ex.what(), 400); }
        // controller
        try {
            auto ctl = app.pipelineController();
            if (!ctl) return errorResponse("control-plane disabled", 503);
            auto st = ctl->HotSwapModel(name, node, uri);
            if (!st.ok()) {
                int code = 409;
                if (st.message().rfind("invalid:", 0) == 0) code = 400;
                else if (st.message().rfind("not_found:", 0) == 0) code = 404;
                else if (st.message().rfind("internal:", 0) == 0) code = 500;
                return errorResponse(st.message(), code);
            }
        } catch (const std::exception& ex) { return errorResponse(std::string("hotswap: ") + ex.what(), 500); }
        // serialize
        try {
            Json::Value ok = successPayload(); ok["hotswapped"] = true; ok["name"] = name; ok["node"] = node; return jsonResponse(ok, 200);
        } catch (const std::exception& ex) { return errorResponse(std::string("serialize: ") + ex.what(), 500); }
#else
        return errorResponse("control-plane disabled", 503);
#endif
    }

    HttpResponse RestServer::Impl::handleCpRemove(const HttpRequest& req) {
#if defined(USE_GRPC) && defined(VA_ENABLE_GRPC_SERVER)
        try {
            // 支持 query: ?name=xxx 或 ?pipeline_name=xxx
            auto kv = parseQueryKV(req.query);
            std::string name;
            if (auto it = kv.find("name"); it != kv.end()) name = it->second;
            if (auto it = kv.find("pipeline_name"); it != kv.end()) name = it->second;
            if (name.empty()) return errorResponse("Missing pipeline name", 400);
            std::string err;
            if (!app.removePipeline(name, &err)) {
                // 404 for not found, otherwise 409
                int code = (err.find("not found") != std::string::npos) ? 404 : 409;
                return errorResponse(err.empty()? "remove failed" : err, code);
            }
            Json::Value ok = successPayload(); ok["removed"] = true; ok["name"] = name; return jsonResponse(ok, 200);
        } catch (const std::exception& ex) { return errorResponse(std::string("exception: ") + ex.what(), 500); }
#else
        return errorResponse("control-plane disabled", 503);
#endif
    }

    HttpResponse RestServer::Impl::handleOrchAttachApply(const HttpRequest& req) {
        // Body: { id, uri, pipeline_name, [yaml_path|graph_id|template_id], [profile], [model_id] }
        try {
            Json::Value body = parseJson(req.body);
            auto getStr = [&](const char* k) { return (body.isMember(k) && body[k].isString()) ? body[k].asString() : std::string(); };
            std::string id = getStr("id");
            std::string uri = getStr("uri");
            std::string pipeline = getStr("pipeline_name");
            std::string yaml = getStr("yaml_path");
            std::string gid = getStr("graph_id");
            std::string tpl = getStr("template_id");
            if (id.empty() || uri.empty() || pipeline.empty() || (yaml.empty() && gid.empty() && tpl.empty())) {
                return errorResponse("missing id/uri/pipeline_name or graph/yaml/template", 400);
            }
            // call VSM attach via gRPC (internal)
#if defined(USE_GRPC)
            std::string vsm_addr = std::getenv("VA_VSM_ADDR") ? std::getenv("VA_VSM_ADDR") : std::string("127.0.0.1:7070");
            std::string attach_err;
            if (!vsmGrpcAttach(vsm_addr, id, uri, getStr("profile"), getStr("model_id"), &attach_err)) {
                return errorResponse(std::string("attach failed via VSM: ") + (attach_err.empty()?"unknown":attach_err), 409);
            }
#else
            return errorResponse("control-plane disabled", 503);
#endif
            // Apply pipeline locally (reusing CP logic)
#if defined(USE_GRPC) && defined(VA_ENABLE_GRPC_SERVER)
            try {
                va::control::PlainPipelineSpec spec; spec.name = pipeline; spec.yaml_path = yaml; spec.graph_id = gid; spec.template_id = tpl;
                std::string err; bool ok = app.applyPipeline(spec, &err);
                if (!ok) return errorResponse(err.empty()? "apply failed" : err, 409);
                Json::Value payload = successPayload(); return jsonResponse(payload, 200);
            } catch (const std::exception& ex) { return errorResponse(std::string("apply: ") + ex.what(), 500); }
#else
            return errorResponse("control-plane disabled", 503);
#endif
        } catch (const std::exception& ex) {
            return errorResponse(std::string("parse: ") + ex.what(), 400);
        }
    }

    HttpResponse RestServer::Impl::handleOrchDetachRemove(const HttpRequest& req) {
        try {
            Json::Value body = parseJson(req.body);
            auto getStr = [&](const char* k) { return (body.isMember(k) && body[k].isString()) ? body[k].asString() : std::string(); };
            std::string id = getStr("id"); std::string pipeline = getStr("pipeline_name");
            if (id.empty() || pipeline.empty()) return errorResponse("missing id/pipeline_name", 400);
            // call VSM delete via gRPC (best-effort)
#if defined(USE_GRPC)
            std::string vsm_addr = std::getenv("VA_VSM_ADDR") ? std::getenv("VA_VSM_ADDR") : std::string("127.0.0.1:7070");
            std::string del_err; (void)vsmGrpcDetach(vsm_addr, id, &del_err);
#else
            return errorResponse("control-plane disabled", 503);
#endif
#if defined(USE_GRPC) && defined(VA_ENABLE_GRPC_SERVER)
            try {
                std::string err; if (!app.removePipeline(pipeline, &err)) return errorResponse(err.empty()? "remove failed" : err, 409);
                Json::Value ok = successPayload(); return jsonResponse(ok, 200);
            } catch (const std::exception& ex) { return errorResponse(std::string("remove: ") + ex.what(), 500); }
#else
            return errorResponse("control-plane disabled", 503);
#endif
        } catch (const std::exception& ex) { return errorResponse(std::string("parse: ") + ex.what(), 400); }
    }

HttpResponse RestServer::Impl::handleOrchHealth(const HttpRequest&) {
    // Aggregate VSM source snapshot + VA system info
    Json::Value vsm(Json::objectValue); int total=0, running=0;
    if (auto snap = vsm_sources_snapshot(2000)) {
        if (snap->isArray()) {
            total = static_cast<int>(snap->size());
            for (const auto& it : *snap) {
                std::string phase = it.isObject() && it.isMember("phase") ? it["phase"].asString() : std::string();
                if (phase == "Ready" || phase == "Running") running++;
            }
        }
    }
    vsm["total"] = total; vsm["running"] = running;
    // Call local system info handler
    HttpRequest r; r.method = "GET"; r.path = "/api/system/info"; r.query = ""; r.headers = {}; r.body = ""; r.params = {};
    auto sys = handleSystemInfo(r);
    Json::Value va(Json::objectValue);
    try {
        Json::CharReaderBuilder b; std::string errs; std::istringstream iss(sys.body); Json::Value root; if (Json::parseFromStream(b, iss, &root, &errs)) va = root;
    } catch (...) {}
    Json::Value payload = successPayload(); Json::Value data(Json::objectValue); data["vsm"] = vsm; data["va"] = va; payload["data"] = data; return jsonResponse(payload, 200);
}

    HttpResponse RestServer::Impl::handleCpStatus(const HttpRequest& req) {
#if defined(USE_GRPC) && defined(VA_ENABLE_GRPC_SERVER)
        try {
            auto kv = parseQueryKV(req.query);
            std::string name;
            if (auto it = kv.find("name"); it != kv.end()) name = it->second;
            if (auto it = kv.find("pipeline_name"); it != kv.end()) name = it->second;
            if (name.empty()) return errorResponse("Missing pipeline name", 400);
            std::string js = app.getPipelineStatus(name);
            // 尝试将内部 JSON 合并到 data 字段
            Json::Value payload = successPayload();
            Json::Value data(Json::objectValue);
            try {
                Json::CharReaderBuilder b; std::string errs; std::istringstream is(js); Json::Value inner;
                if (Json::parseFromStream(b, is, &inner, &errs)) { data = inner; }
                else { data["raw"] = js; data["parse_error"] = errs; }
            } catch (...) { data["raw"] = js; }
            payload["data"] = data; payload["name"] = name; return jsonResponse(payload, 200);
        } catch (const std::exception& ex) { return errorResponse(std::string("exception: ") + ex.what(), 500); }
#else
        return errorResponse("control-plane disabled", 503);
#endif
    }

    HttpResponse RestServer::Impl::handleCpDrain(const HttpRequest& req) {
#if defined(USE_GRPC) && defined(VA_ENABLE_GRPC_SERVER)
        try {
            Json::Value body = parseJson(req.body);
            if (!body.isMember("pipeline_name") || !body["pipeline_name"].isString()) {
                return errorResponse("Missing required field: pipeline_name", 400);
            }
            std::string name = body["pipeline_name"].asString();
            int timeout_sec = 10;
            if (body.isMember("timeout_sec") && body["timeout_sec"].isInt()) timeout_sec = body["timeout_sec"].asInt();
            std::string err;
            if (!app.drainPipeline(name, timeout_sec, &err)) {
                int code = (err.find("not found") != std::string::npos) ? 404 : 409;
                return errorResponse(err.empty()? "drain failed" : err, code);
            }
            Json::Value ok = successPayload(); ok["drained"] = true; ok["name"] = name; ok["timeout_sec"] = timeout_sec; return jsonResponse(ok, 200);
        } catch (const std::exception& ex) { return errorResponse(std::string("exception: ") + ex.what(), 500); }
#else
        return errorResponse("control-plane disabled", 503);
#endif
    }

} // namespace va::server
