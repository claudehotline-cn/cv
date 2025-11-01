#include "server/rest_impl.hpp"

namespace va::server {

// --- WHEP handlers ---
HttpResponse RestServer::Impl::handleWhepCors(const HttpRequest&) {
    HttpResponse resp; resp.status_code = 204;
    resp.headers["Access-Control-Allow-Origin"] = "*";
    resp.headers["Access-Control-Allow-Methods"] = "POST, PATCH, DELETE, OPTIONS";
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization";
    resp.headers["Access-Control-Expose-Headers"] = "Location";
    resp.body.clear();
    return resp;
}

// --- WHEP routing helpers (gRPC to VA or local fallback) ---
std::vector<std::string> RestServer::Impl::parseHosts(const char* envName) {
    std::vector<std::string> out; const char* p = std::getenv(envName); if(!p) return out; std::string s(p); size_t pos=0; while(pos < s.size()) { auto c=s.find(',',pos); auto t=(c==std::string::npos)? s.substr(pos): s.substr(pos,c-pos); pos=(c==std::string::npos)? s.size(): c+1; if(!t.empty()) out.push_back(t); } return out; }

std::string RestServer::Impl::pickHost(const std::vector<std::string>& hosts, const std::string& key) { if(hosts.empty()) return std::string(); auto h = std::hash<std::string>{}(key); return hosts[h % hosts.size()]; }

std::unique_ptr<va::whep::WhepControl::Stub> RestServer::Impl::makeWhepStub(const std::string& addr) { grpc::ChannelArguments args; args.SetInt("grpc.keepalive_time_ms", 30000); args.SetInt("grpc.keepalive_timeout_ms", 10000); auto ch = grpc::CreateCustomChannel(addr, grpc::InsecureChannelCredentials(), args); return va::whep::WhepControl::NewStub(ch); }

bool RestServer::Impl::grpcWhepAdd(const std::string& addr, const std::string& stream, const std::string& offer, std::string* sid, std::string* answer) { try{ auto stub = makeWhepStub(addr); grpc::ClientContext ctx; ctx.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(8000)); va::whep::AddWhepSessionRequest req; req.set_stream_id(stream); req.set_offer_sdp(offer); va::whep::AddWhepSessionReply rep; auto st = stub->AddWhepSession(&ctx, req, &rep); if(!st.ok()||!rep.ok()) return false; if(sid) *sid = rep.session_id(); if(answer) *answer = rep.answer_sdp(); return true; }catch(...) { return false; } }

bool RestServer::Impl::grpcWhepPatch(const std::string& addr, const std::string& sid, const std::string& frag) { try{ auto stub = makeWhepStub(addr); grpc::ClientContext ctx; ctx.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(4000)); va::whep::PatchWhepCandidateRequest req; req.set_session_id(sid); req.set_sdp_frag(frag); va::whep::PatchWhepCandidateReply rep; auto st=stub->PatchWhepCandidate(&ctx, req, &rep); return st.ok() && rep.ok(); }catch(...) { return false; } }

bool RestServer::Impl::grpcWhepDel(const std::string& addr, const std::string& sid) { try{ auto stub = makeWhepStub(addr); grpc::ClientContext ctx; ctx.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(4000)); va::whep::DeleteWhepSessionRequest req; req.set_session_id(sid); va::whep::DeleteWhepSessionReply rep; auto st=stub->DeleteWhepSession(&ctx, req, &rep); return st.ok() && rep.ok(); }catch(...) { return false; } }

std::string RestServer::Impl::genCpSid() { static std::atomic<uint64_t> ctr{1}; std::ostringstream oss; oss<<std::hex<< (uint64_t)std::time(nullptr) << ctr.fetch_add(1); return oss.str(); }

HttpResponse RestServer::Impl::handleWhepCreate(const HttpRequest& req) {
    try {
        std::string offer = req.body;
        auto q = parseQueryKV(req.query);
        std::string stream = q.count("stream")? q["stream"] : (q.count("stream_id")? q["stream_id"] : std::string());
        if (stream.empty() || offer.empty()) return errorResponse("missing stream/sdp", 400);
        // Variant selection: overlay (default) → use full stream (e.g. cam01:det_720p);
        // raw → strip profile suffix (use cam01) 以转发原始帧。
        std::string variant;
        if (q.count("variant")) {
            variant = q["variant"];
        } else {
            // prefer app config, then env
            try { variant = va::server::toLower(app.appConfig().sfu_whep_default_variant); } catch (...) {}
            if (variant.empty()) {
                const char* v = std::getenv("VA_WHEP_DEFAULT_VARIANT");
                if (v) variant = v;
            }
        }
        for (auto& ch : variant) ch = (char)std::tolower((unsigned char)ch);
        if (variant != "raw" && variant != "overlay") variant = "overlay";
        std::string streamKey = stream;
        if (variant == "raw") { auto p = streamKey.find(':'); if (p != std::string::npos) streamKey = streamKey.substr(0, p); }
        // choose VA instance by hashing
        std::vector<std::string> hosts = parseHosts("VA_GRPC_HOSTS");
        std::string addr = hosts.empty()? (std::getenv("VA_GRPC_ADDR")? std::getenv("VA_GRPC_ADDR") : std::string()) : pickHost(hosts, streamKey);
        VA_LOG_C(::va::core::LogLevel::Info, "rest.whep") << "POST /whep streamKey='" << streamKey
            << "' offer_len=" << offer.size() << " hosts=" << hosts.size() << (addr.empty()? " addr=<local>" : (" addr="+addr));
        // Debug: log a short preview of Offer SDP
        {
            std::string snip = offer.substr(0, 240);
            for (auto& ch : snip) { if (ch=='\r' || ch=='\n') ch=' '; }
            VA_LOG_C(::va::core::LogLevel::Debug, "rest.whep") << "offer_sdp_head=" << snip;
        }
        std::string answer, va_sid, cp_sid;
        int st_code = 0; bool ok = false;
        if (!addr.empty()) {
            ok = grpcWhepAdd(addr, streamKey, offer, &va_sid, &answer);
            st_code = ok ? 201 : 502;
        }
        if (!ok) {
            int st = va::media::WhepSessionManager::instance().createSession(streamKey, offer, answer, va_sid);
            st_code = st; ok = (st == 201);
        }
        if (!ok) {
            VA_LOG_C(::va::core::LogLevel::Error, "rest.whep") << "POST /whep failed streamKey='" << streamKey << "' status=" << st_code;
            return errorResponse("whep create failed", st_code > 0 ? st_code : 500);
        }
        cp_sid = genCpSid();
        {
            std::lock_guard<std::mutex> lk(whep_mu_); whep_map_[cp_sid] = std::make_pair(addr, va_sid);
        }
        VA_LOG_C(::va::core::LogLevel::Info, "rest.whep") << "POST /whep created cp_sid=" << cp_sid << " va_sid=" << va_sid
            << " answer_len=" << answer.size();
        // Debug: log a short preview of Answer SDP
        {
            std::string snip = answer.substr(0, 240);
            for (auto& ch : snip) { if (ch=='\r' || ch=='\n') ch=' '; }
            VA_LOG_C(::va::core::LogLevel::Debug, "rest.whep") << "answer_sdp_head=" << snip;
        }
        HttpResponse resp; resp.status_code = 201; resp.headers["Content-Type"] = "application/sdp"; resp.headers["Access-Control-Allow-Origin"] = "*"; resp.headers["Access-Control-Expose-Headers"] = "Location"; resp.headers["Location"] = std::string("/whep/sessions/") + cp_sid; resp.body = answer; return resp;
    } catch (const std::exception& ex) { return errorResponse(std::string("whep: ") + ex.what(), 400); }
}

HttpResponse RestServer::Impl::handleWhepPatch(const HttpRequest& req) {
    auto it = req.params.find("sid"); if (it == req.params.end()) return errorResponse("missing sid", 400);
    std::string sid = it->second; std::string addr, va_sid;
    {
        std::lock_guard<std::mutex> lk(whep_mu_); auto f = whep_map_.find(sid); if (f != whep_map_.end()) { addr = f->second.first; va_sid = f->second.second; }
    }
    VA_LOG_C(::va::core::LogLevel::Debug, "rest.whep") << "PATCH /whep/sessions sid=" << sid
        << " body_len=" << req.body.size() << (addr.empty()? " route=local" : (" route=grpc:"+addr));
    // Debug: log short preview of ICE fragment
    {
        std::string snip = req.body.substr(0, 200);
        for (auto& ch : snip) { if (ch=='\r' || ch=='\n') ch=' '; }
        VA_LOG_C(::va::core::LogLevel::Debug, "rest.whep") << "patch_frag_head=" << snip;
    }
    bool ok = false; if (!addr.empty()) ok = grpcWhepPatch(addr, va_sid, req.body); if (!ok) { int st = va::media::WhepSessionManager::instance().patchSession(va_sid.empty()? sid : va_sid, req.body); ok = (st==204); }
    VA_LOG_C(::va::core::LogLevel::Info, "rest.whep") << "PATCH /whep/sessions sid=" << sid << " -> status=" << (ok?204:404);
    HttpResponse resp; resp.status_code = ok? 204 : 404; resp.headers["Access-Control-Allow-Origin"] = "*"; resp.body.clear(); return resp;
}

HttpResponse RestServer::Impl::handleWhepDelete(const HttpRequest& req) {
    auto it = req.params.find("sid"); if (it == req.params.end()) return errorResponse("missing sid", 400);
    std::string sid = it->second; std::string addr, va_sid;
    {
        std::lock_guard<std::mutex> lk(whep_mu_); auto f = whep_map_.find(sid); if (f != whep_map_.end()) { addr = f->second.first; va_sid = f->second.second; whep_map_.erase(f); }
    }
    VA_LOG_C(::va::core::LogLevel::Debug, "rest.whep") << "DELETE /whep/sessions sid=" << sid
        << (addr.empty()? " route=local" : (" route=grpc:"+addr));
    bool ok = false; if (!addr.empty()) ok = grpcWhepDel(addr, va_sid); if (!ok) { int st = va::media::WhepSessionManager::instance().deleteSession(va_sid.empty()? sid : va_sid); ok = (st==204); }
    VA_LOG_C(::va::core::LogLevel::Info, "rest.whep") << "DELETE /whep/sessions sid=" << sid << " -> status=" << (ok?204:404);
    HttpResponse resp; resp.status_code = ok? 204 : 404; resp.headers["Access-Control-Allow-Origin"] = "*"; resp.body.clear(); return resp;
}

} // namespace va::server
