        rest_server_->stop();
        rest_server_.reset();
    }
#if defined(USE_GRPC) && defined(VA_ENABLE_GRPC_SERVER)
    grpc_server_.reset();
    pipeline_controller_.reset();
    graph_adapter_.reset();
#endif

#if defined(USE_GRPC)
    vsm_watch_stop_.store(true);
    if (vsm_watch_thread_ && vsm_watch_thread_->joinable()) {
        vsm_watch_thread_->join();
    }
    vsm_watch_thread_.reset();
#endif

    track_manager_.reset();
    pipeline_builder_.reset();

    initialized_ = false;
}

bool Application::isInitialized() const {
    return initialized_;
}

#if defined(USE_GRPC)
void Application::startVsmWatchIfConfigured() {
    std::string addr = app_config_.control_plane.vsm_addr;
    if (const char* ep = std::getenv("VA_VSM_ADDR")) { addr = ep; }
    if (addr.empty()) {
        return; // not configured
    }
    if (vsm_watch_thread_) return;

    // choose default profile
    auto default_profile = std::string{};
    for (const auto& p : profiles_) {
        if (p.name == "det_720p") { default_profile = p.name; break; }
    }
    if (default_profile.empty() && !profiles_.empty()) default_profile = profiles_.front().name;
    if (default_profile.empty()) default_profile = "det_720p";

    int interval_ms = app_config_.control_plane.watch_interval_ms;
    if (const char* v = std::getenv("VA_VSM_WATCH_MS")) { try { int t = std::stoi(v); if (t>0) interval_ms = t; } catch (...) {} }

    vsm_watch_stop_.store(false);
    vsm_watch_thread_ = std::make_unique<std::thread>([this, addr, default_profile, interval_ms]() {
        VA_LOG_INFO() << "[ControlPlane] VSM watch connecting addr=" << addr << " interval_ms=" << interval_ms;
        while (!vsm_watch_stop_.load()) {
            try {
                // gRPC channel with optional keepalive
                grpc::ChannelArguments args;
                auto env_int = [](const char* k, int defv){ if(const char* v=getenv(k)){ try { return std::stoi(v);} catch(...){} } return defv;};
                int ka_time = app_config_.control_plane.keepalive_time_ms; ka_time = env_int("VA_VSM_KEEPALIVE_TIME_MS", ka_time);
                int ka_timeout = app_config_.control_plane.keepalive_timeout_ms; ka_timeout = env_int("VA_VSM_KEEPALIVE_TIMEOUT_MS", ka_timeout);
                int ka_permit = app_config_.control_plane.keepalive_permit_without_calls ? 1 : 0; ka_permit = env_int("VA_VSM_KEEPALIVE_PERMIT_WITHOUT_CALLS", ka_permit);
                args.SetInt("grpc.keepalive_time_ms", ka_time);
                args.SetInt("grpc.keepalive_timeout_ms", ka_timeout);
                args.SetInt("grpc.keepalive_permit_without_calls", ka_permit);
                auto channel = grpc::CreateCustomChannel(addr, grpc::InsecureChannelCredentials(), args);
                std::unique_ptr<vsm::v1::SourceControl::Stub> stub = vsm::v1::SourceControl::NewStub(channel);
                grpc::ClientContext ctx;
                // Set a generous deadline to detect dead streams
                int deadline_ms = app_config_.control_plane.watch_deadline_ms; deadline_ms = env_int("VA_VSM_WATCH_DEADLINE_MS", deadline_ms);
                auto ddl = std::chrono::system_clock::now() + std::chrono::milliseconds(deadline_ms);
                ctx.set_deadline(ddl);
                vsm::v1::WatchStateRequest req; req.set_interval_ms(interval_ms);
                std::unique_ptr<grpc::ClientReader<vsm::v1::WatchStateReply>> reader(stub->WatchState(&ctx, req));
                struct Item { std::string uri; std::string profile; std::string model; };
                std::unordered_map<std::string, Item> last; // attach_id -> {uri,profile,model}
                std::unordered_map<std::string, long long> last_change_ms;
                auto now_ms = [](){ return (long long)std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count(); };
                int debounce_ms = 300; if (const char* v = std::getenv("VA_VSM_DEBOUNCE_MS")) { try { int t = std::stoi(v); if (t>=0) debounce_ms = t; } catch (...) {} }
                vsm::v1::WatchStateReply rep;
                bool had_data = false;
                while (!vsm_watch_stop_.load() && reader->Read(&rep)) {
                    had_data = true;
                    std::unordered_map<std::string, Item> cur;
                    cur.reserve(static_cast<size_t>(rep.items_size()));
