#pragma once
#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>
#include <mutex>

namespace va { namespace core {

// Minimal CodecRegistry for metrics only (no caching/LRU).
class CodecRegistry {
public:
    struct SnapshotKV { std::string impl; uint64_t value; };
    struct Snapshot {
        uint64_t decoder_build_total{0};
        uint64_t decoder_hit_total{0};
        uint64_t encoder_build_total{0};
        uint64_t encoder_hit_total{0};
        std::vector<SnapshotKV> decoder_build_by_impl;
        std::vector<SnapshotKV> decoder_hit_by_impl;
        std::vector<SnapshotKV> encoder_build_by_impl;
        std::vector<SnapshotKV> encoder_hit_by_impl;
    };

    static void noteDecoderBuild(const std::string& impl);
    static void noteDecoderHit(const std::string& impl);
    static void noteEncoderBuild(const std::string& impl);
    static void noteEncoderHit(const std::string& impl);

    static Snapshot snapshot();

private:
    static void inc(std::unordered_map<std::string, uint64_t>& m, const std::string& k, uint64_t* total);
    static std::vector<SnapshotKV> toVec(const std::unordered_map<std::string, uint64_t>& m);
    static std::mutex& mu();
    static std::unordered_map<std::string, uint64_t>& d_build();
    static std::unordered_map<std::string, uint64_t>& d_hit();
    static std::unordered_map<std::string, uint64_t>& e_build();
    static std::unordered_map<std::string, uint64_t>& e_hit();
    static uint64_t& d_build_total();
    static uint64_t& d_hit_total();
    static uint64_t& e_build_total();
    static uint64_t& e_hit_total();
};

} } // namespace va::core

