          }
      }

      // --- WHEP handlers ---
      HttpResponse handleWhepCors(const HttpRequest&) {
          HttpResponse resp; resp.status_code = 204;
          resp.headers["Access-Control-Allow-Origin"] = "*";
          resp.headers["Access-Control-Allow-Methods"] = "POST, PATCH, DELETE, OPTIONS";
          resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization";
          resp.headers["Access-Control-Expose-Headers"] = "Location";
          resp.body.clear();
          return resp;
      }

      // --- WHEP routing helpers (gRPC to VA or local fallback) ---
      static std::vector<std::string> parseHosts(const char* envName){
          std::vector<std::string> out; const char* p = std::getenv(envName); if(!p) return out; std::string s(p); size_t pos=0; while(pos < s.size()){ auto c=s.find(',',pos); auto t=(c==std::string::npos)? s.substr(pos): s.substr(pos,c-pos); pos=(c==std::string::npos)? s.size(): c+1; if(!t.empty()) out.push_back(t); } return out; }
      static std::string pickHost(const std::vector<std::string>& hosts, const std::string& key){ if(hosts.empty()) return std::string(); auto h = std::hash<std::string>{}(key); return hosts[h % hosts.size()]; }
      static std::unique_ptr<va::whep::WhepControl::Stub> makeWhepStub(const std::string& addr){ grpc::ChannelArguments args; args.SetInt("grpc.keepalive_time_ms", 30000); args.SetInt("grpc.keepalive_timeout_ms", 10000); auto ch = grpc::CreateCustomChannel(addr, grpc::InsecureChannelCredentials(), args); return va::whep::WhepControl::NewStub(ch); }
      static bool grpcWhepAdd(const std::string& addr, const std::string& stream, const std::string& offer, std::string* sid, std::string* answer){ try{ auto stub = makeWhepStub(addr); grpc::ClientContext ctx; ctx.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(8000)); va::whep::AddWhepSessionRequest req; req.set_stream_id(stream); req.set_offer_sdp(offer); va::whep::AddWhepSessionReply rep; auto st = stub->AddWhepSession(&ctx, req, &rep); if(!st.ok()||!rep.ok()) return false; if(sid) *sid = rep.session_id(); if(answer) *answer = rep.answer_sdp(); return true; }catch(...){ return false; } }
      static bool grpcWhepPatch(const std::string& addr, const std::string& sid, const std::string& frag){ try{ auto stub = makeWhepStub(addr); grpc::ClientContext ctx; ctx.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(4000)); va::whep::PatchWhepCandidateRequest req; req.set_session_id(sid); req.set_sdp_frag(frag); va::whep::PatchWhepCandidateReply rep; auto st=stub->PatchWhepCandidate(&ctx, req, &rep); return st.ok() && rep.ok(); }catch(...){ return false; } }
      static bool grpcWhepDel(const std::string& addr, const std::string& sid){ try{ auto stub = makeWhepStub(addr); grpc::ClientContext ctx; ctx.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(4000)); va::whep::DeleteWhepSessionRequest req; req.set_session_id(sid); va::whep::DeleteWhepSessionReply rep; auto st=stub->DeleteWhepSession(&ctx, req, &rep); return st.ok() && rep.ok(); }catch(...){ return false; } }

      std::mutex whep_mu_;
      std::unordered_map<std::string, std::pair<std::string,std::string>> whep_map_; // cp_sid -> {addr, va_sid}
      static std::string genCpSid(){ static std::atomic<uint64_t> ctr{1}; std::ostringstream oss; oss<<std::hex<< (uint64_t)std::time(nullptr) << ctr.fetch_add(1); return oss.str(); }

      HttpResponse handleWhepCreate(const HttpRequest& req) {
          try {
              std::string offer = req.body;
              auto q = parseQueryKV(req.query);
              std::string stream = q.count("stream")? q["stream"] : (q.count("stream_id")? q["stream_id"] : std::string());
              if (stream.empty() || offer.empty()) return errorResponse("missing stream/sdp", 400);
              std::string streamKey = stream; auto p = streamKey.find(':'); if (p != std::string::npos) streamKey = streamKey.substr(0, p);
              // choose VA instance by hashing
              std::vector<std::string> hosts = parseHosts("VA_GRPC_HOSTS");
              std::string addr = hosts.empty()? (std::getenv("VA_GRPC_ADDR")? std::getenv("VA_GRPC_ADDR") : std::string()) : pickHost(hosts, streamKey);
              std::string answer, va_sid, cp_sid;
              bool ok = false;
              if (!addr.empty()) {
                  ok = grpcWhepAdd(addr, streamKey, offer, &va_sid, &answer);
              }
              if (!ok) {
                  int st = va::media::WhepSessionManager::instance().createSession(streamKey, offer, answer, va_sid);
                  ok = (st == 201);
              }
              if (!ok) return errorResponse("whep create failed", 500);
              cp_sid = genCpSid();
              {
                  std::lock_guard<std::mutex> lk(whep_mu_); whep_map_[cp_sid] = std::make_pair(addr, va_sid);
              }
              HttpResponse resp; resp.status_code = 201; resp.headers["Content-Type"] = "application/sdp"; resp.headers["Access-Control-Allow-Origin"] = "*"; resp.headers["Access-Control-Expose-Headers"] = "Location"; resp.headers["Location"] = std::string("/whep/sessions/") + cp_sid; resp.body = answer; return resp;
          } catch (const std::exception& ex) { return errorResponse(std::string("whep: ") + ex.what(), 400); }
      }

      HttpResponse handleWhepPatch(const HttpRequest& req) {
          auto it = req.params.find("sid"); if (it == req.params.end()) return errorResponse("missing sid", 400);
          std::string sid = it->second; std::string addr, va_sid;
          {
              std::lock_guard<std::mutex> lk(whep_mu_); auto f = whep_map_.find(sid); if (f != whep_map_.end()) { addr = f->second.first; va_sid = f->second.second; }
          }
          bool ok = false; if (!addr.empty()) ok = grpcWhepPatch(addr, va_sid, req.body); if (!ok) { int st = va::media::WhepSessionManager::instance().patchSession(va_sid.empty()? sid : va_sid, req.body); ok = (st==204); }
          HttpResponse resp; resp.status_code = ok? 204 : 404; resp.headers["Access-Control-Allow-Origin"] = "*"; resp.body.clear(); return resp;
      }

      HttpResponse handleWhepDelete(const HttpRequest& req) {
          auto it = req.params.find("sid"); if (it == req.params.end()) return errorResponse("missing sid", 400);
          std::string sid = it->second; std::string addr, va_sid;
          {
