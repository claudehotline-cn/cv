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
                    for (const auto& it : rep.items()) {
                        Item item{it.source_uri(), it.profile(), it.model_id()};
                        cur[it.attach_id()] = item;
                    }
                    // create/update
                    for (const auto& kv : cur) {
                        const std::string& sid = kv.first; const Item& item = kv.second;
                        const std::string prof = item.profile.empty()? default_profile : item.profile;
                        // find existing pipeline
                        bool exists = false; std::string exist_uri; std::string exist_model;
                        for (const auto& pinfo : track_manager_->listPipelines()) {
                            if (pinfo.stream_id == sid && pinfo.profile_id == prof) {
                                exists = true; exist_uri = pinfo.source_uri; exist_model = pinfo.model_id; break;
                            }
                        }
                        long long nowts = now_ms();
                        auto too_soon = [&](const std::string& key){ auto it=last_change_ms.find(key); return it!=last_change_ms.end() && (nowts - it->second) < debounce_ms; };
                        auto mark = [&](const std::string& key){ last_change_ms[key]=nowts; };

                        if (!exists) {
                            if (!too_soon(sid+":"+prof)) {
                                auto key = subscribeStream(sid, prof, item.uri);
                                if (key) {
                                    VA_LOG_INFO() << "[ControlPlane] auto-subscribe created key=" << *key << " stream=" << sid << " profile=" << prof;
                                    va::core::GlobalMetrics::cp_auto_subscribe_total.fetch_add(1);
                                } else {
                                    VA_LOG_WARN() << "[ControlPlane] auto-subscribe failed stream=" << sid << " err=" << last_error_;
                                    va::core::GlobalMetrics::cp_auto_subscribe_failed_total.fetch_add(1);
                                }
                                mark(sid+":"+prof);
                            }
                        } else {
                            // exists: if uri changed, switch source
                            if (!exist_uri.empty() && exist_uri != item.uri) {
                                if (!too_soon(std::string("sw:")+sid+":"+prof)) {
                                    bool ok = switchSource(sid, prof, item.uri);
                                    if (ok) { VA_LOG_INFO() << "[ControlPlane] auto-switchSource stream=" << sid << " profile=" << prof; va::core::GlobalMetrics::cp_auto_switch_source_total.fetch_add(1);} 
                                    else { VA_LOG_WARN() << "[ControlPlane] auto-switchSource failed stream=" << sid << " err=" << last_error_; va::core::GlobalMetrics::cp_auto_switch_source_failed_total.fetch_add(1);} 
                                    mark(std::string("sw:")+sid+":"+prof);
                                }
                            }
                            // exists: if model changed and provided, switch model
                            if (!item.model.empty() && exist_model != item.model) {
                                if (!too_soon(std::string("md:")+sid+":"+prof)) {
                                    bool okm = switchModel(sid, prof, item.model);
                                    if (okm) {
                                        VA_LOG_INFO() << "[ControlPlane] auto-switchModel stream=" << sid << " profile=" << prof << " model=" << item.model;
                                        va::core::GlobalMetrics::cp_auto_switch_model_total.fetch_add(1);
                                        mark(std::string("md:")+sid+":"+prof);
                                    } else {
                                        VA_LOG_WARN() << "[ControlPlane] auto-switchModel failed stream=" << sid << " model=" << item.model << " err=" << last_error_;
                                        va::core::GlobalMetrics::cp_auto_switch_model_failed_total.fetch_add(1);
                                        // 不标记md:去抖键，允许下一次WatchState重试
                                    }
                                }
                            }
                        }
                    }
                    // remove
                    long long nowts2 = now_ms();
                    auto too_soon2 = [&](const std::string& key){ auto it=last_change_ms.find(key); return it!=last_change_ms.end() && (nowts2 - it->second) < debounce_ms; };
                    auto mark2 = [&](const std::string& key){ last_change_ms[key]=nowts2; };
                    for (const auto& kv : last) {
                        if (cur.find(kv.first) == cur.end()) {
                            const std::string prof = kv.second.profile.empty()? default_profile : kv.second.profile;
                            if (!too_soon2(std::string("rm:")+kv.first+":"+prof)) {
                                unsubscribeStream(kv.first, prof);
                                VA_LOG_INFO() << "[ControlPlane] auto-unsubscribe stream=" << kv.first << " profile=" << prof;
                                va::core::GlobalMetrics::cp_auto_unsubscribe_total.fetch_add(1);
                                mark2(std::string("rm:")+kv.first+":"+prof);
                            }
                        }
                    }
                    last.swap(cur);
                }
                // reset backoff on activity; else apply backoff with jitter
                static int backoff_ms = app_config_.control_plane.backoff_start_ms; backoff_ms = env_int("VA_VSM_BACKOFF_MS_START", backoff_ms);
                static int backoff_max = app_config_.control_plane.backoff_max_ms; backoff_max = env_int("VA_VSM_BACKOFF_MS_MAX", backoff_max);
                static double jitter = app_config_.control_plane.backoff_jitter; if(const char* j=getenv("VA_VSM_BACKOFF_JITTER")) { try { jitter = std::stod(j);} catch(...){} }
                if (!had_data) {
                    int delay = backoff_ms;
                    // jitter +/-
                    int jspan = static_cast<int>(delay * jitter);
                    if (jspan > 0) {
                        auto seed = static_cast<unsigned>(now_ms());
                        int delta = (seed % (2*jspan+1)) - jspan; // [-jspan, +jspan]
                        delay = std::max(0, delay + delta);
                    }
                    std::this_thread::sleep_for(std::chrono::milliseconds(delay));
                    backoff_ms = std::min(backoff_ms * 2, backoff_max);
                } else {
                    backoff_ms = env_int("VA_VSM_BACKOFF_MS_START", 500);
                }
            } catch (const std::exception& ex) {
                VA_LOG_WARN() << "[ControlPlane] VSM watch exception: " << ex.what();
                // keep same backoff path as above when exceptions occur
                static int backoff_ms = app_config_.control_plane.backoff_start_ms; static int backoff_max = app_config_.control_plane.backoff_max_ms; static double jitter = app_config_.control_plane.backoff_jitter;
                int jspan = static_cast<int>(backoff_ms * jitter);
                int delay = backoff_ms + ((jspan>0)? ((int)(std::chrono::steady_clock::now().time_since_epoch().count()) % (2*jspan+1)) - jspan : 0);
                std::this_thread::sleep_for(std::chrono::milliseconds(std::max(0, delay)));
