    // parse status line
    int status = 0; {
        auto crlf = resp.find("\r\n"); if (crlf != std::string::npos) {
            std::string statusLine = resp.substr(0, crlf);
            auto sp = statusLine.find(' '); if (sp != std::string::npos) {
                auto sp2 = statusLine.find(' ', sp+1); if (sp2 != std::string::npos) {
                    try { status = std::stoi(statusLine.substr(sp+1, sp2-sp-1)); } catch(...) { status = 0; }
                }
            }
        }
    }
    auto pos = resp.find("\r\n\r\n"); std::string body = (pos==std::string::npos? std::string() : resp.substr(pos+4));
    return std::make_pair(status, body);
#else
    (void)host; (void)port; (void)path; (void)json; (void)timeout_ms; return std::nullopt;
#endif
}

static std::optional<Json::Value> vsm_sources_snapshot(int timeout_ms) {
    std::string host = "127.0.0.1";
    int port = 7071;
    if (const char* p = std::getenv("VSM_REST_HOST")) host = p;
    if (const char* p = std::getenv("VSM_REST_PORT")) { try { int v = std::stoi(p); if (v > 0 && v < 65536) port = v; } catch (...) {} }
    auto body = http_get_body(host, port, "/api/source/list", timeout_ms);
    if (!body) return std::nullopt;
    try {
        Json::CharReaderBuilder b; std::string errs; std::istringstream iss(*body); Json::Value root; if (!Json::parseFromStream(b, iss, &root, &errs)) return std::nullopt;
        if (root.isObject() && root.isMember("data") && root["data"].isArray()) return root["data"];
        if (root.isArray()) return root;
    } catch (...) {}
    return std::nullopt;
}

  static std::optional<Json::Value> vsm_source_describe(const std::string& id, int timeout_ms) {
    std::string host = "127.0.0.1";
    int port = 7071;
    if (const char* p = std::getenv("VSM_REST_HOST")) host = p;
    if (const char* p = std::getenv("VSM_REST_PORT")) { try { int v = std::stoi(p); if (v > 0 && v < 65536) port = v; } catch (...) {} }
    std::string path = std::string("/api/source/describe?id=") + id;
    auto body = http_get_body(host, port, path, timeout_ms);
    if (!body) return std::nullopt;
    try {
        Json::CharReaderBuilder b; std::string errs; std::istringstream iss(*body); Json::Value root; if (!Json::parseFromStream(b, iss, &root, &errs)) return std::nullopt;
        if (root.isObject() && root.isMember("data") && root["data"].isObject()) return root["data"];
        if (root.isObject()) return root;
    } catch (...) {}
    return std::nullopt;
  }

#if defined(USE_GRPC)
  // --- VSM gRPC helpers ---
  static std::unique_ptr<vsm::v1::SourceControl::Stub> makeVsmStub(const std::string& addr) {
      grpc::ChannelArguments args; args.SetInt("grpc.keepalive_time_ms", 30000); args.SetInt("grpc.keepalive_timeout_ms", 10000);
      auto ch = grpc::CreateCustomChannel(addr, grpc::InsecureChannelCredentials(), args);
      return vsm::v1::SourceControl::NewStub(ch);
  }
  static bool vsmGrpcAttach(const std::string& addr, const std::string& id, const std::string& uri,
                            const std::string& profile, const std::string& model, std::string* err) {
      try {
          auto stub = makeVsmStub(addr);
          grpc::ClientContext ctx; auto ddl = std::chrono::system_clock::now() + std::chrono::milliseconds(8000); ctx.set_deadline(ddl);
          vsm::v1::AttachRequest req; req.set_attach_id(id); req.set_source_uri(uri); if (!profile.empty()) (*req.mutable_options())["profile"] = profile; if (!model.empty()) (*req.mutable_options())["model_id"] = model;
          vsm::v1::AttachReply rep; auto st = stub->Attach(&ctx, req, &rep);
          if (!st.ok()) { if (err) *err = st.error_message(); return false; }
          return true;
      } catch (const std::exception& ex) { if (err) *err = ex.what(); return false; }
  }
  static bool vsmGrpcDetach(const std::string& addr, const std::string& id, std::string* err) {
      try {
          auto stub = makeVsmStub(addr);
          grpc::ClientContext ctx; auto ddl = std::chrono::system_clock::now() + std::chrono::milliseconds(8000); ctx.set_deadline(ddl);
