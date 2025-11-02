#include "core/codec_registry.hpp"

namespace va { namespace core {

static std::mutex g_mu;
static std::unordered_map<std::string, uint64_t> g_dec_build;
static std::unordered_map<std::string, uint64_t> g_dec_hit;
static std::unordered_map<std::string, uint64_t> g_enc_build;
static std::unordered_map<std::string, uint64_t> g_enc_hit;
static uint64_t g_dec_build_total = 0;
static uint64_t g_dec_hit_total = 0;
static uint64_t g_enc_build_total = 0;
static uint64_t g_enc_hit_total = 0;

std::mutex& CodecRegistry::mu() { return g_mu; }
std::unordered_map<std::string, uint64_t>& CodecRegistry::d_build() { return g_dec_build; }
std::unordered_map<std::string, uint64_t>& CodecRegistry::d_hit() { return g_dec_hit; }
std::unordered_map<std::string, uint64_t>& CodecRegistry::e_build() { return g_enc_build; }
std::unordered_map<std::string, uint64_t>& CodecRegistry::e_hit() { return g_enc_hit; }
uint64_t& CodecRegistry::d_build_total() { return g_dec_build_total; }
uint64_t& CodecRegistry::d_hit_total() { return g_dec_hit_total; }
uint64_t& CodecRegistry::e_build_total() { return g_enc_build_total; }
uint64_t& CodecRegistry::e_hit_total() { return g_enc_hit_total; }

void CodecRegistry::inc(std::unordered_map<std::string, uint64_t>& m, const std::string& k, uint64_t* total) {
    auto it = m.find(k);
    if (it == m.end()) m.emplace(k, 1ull); else it->second += 1ull;
    if (total) (*total) += 1ull;
}

std::vector<CodecRegistry::SnapshotKV> CodecRegistry::toVec(const std::unordered_map<std::string, uint64_t>& m) {
    std::vector<SnapshotKV> v; v.reserve(m.size());
    for (const auto& kv : m) v.push_back({kv.first, kv.second});
    return v;
}

void CodecRegistry::noteDecoderBuild(const std::string& impl) {
    std::lock_guard<std::mutex> lk(mu());
    bool existed = d_build().find(impl) != d_build().end();
    inc(d_build(), impl, &d_build_total());
    if (existed) inc(d_hit(), impl, &d_hit_total());
}
void CodecRegistry::noteDecoderHit(const std::string& impl) {
    std::lock_guard<std::mutex> lk(mu()); inc(d_hit(), impl, &d_hit_total()); }
void CodecRegistry::noteEncoderBuild(const std::string& impl) {
    std::lock_guard<std::mutex> lk(mu());
    bool existed = e_build().find(impl) != e_build().end();
    inc(e_build(), impl, &e_build_total());
    if (existed) inc(e_hit(), impl, &e_hit_total());
}
void CodecRegistry::noteEncoderHit(const std::string& impl) {
    std::lock_guard<std::mutex> lk(mu()); inc(e_hit(), impl, &e_hit_total()); }

CodecRegistry::Snapshot CodecRegistry::snapshot() {
    std::lock_guard<std::mutex> lk(mu());
    Snapshot s;
    s.decoder_build_total = d_build_total();
    s.decoder_hit_total   = d_hit_total();
    s.encoder_build_total = e_build_total();
    s.encoder_hit_total   = e_hit_total();
    s.decoder_build_by_impl = toVec(d_build());
    s.decoder_hit_by_impl   = toVec(d_hit());
    s.encoder_build_by_impl = toVec(e_build());
    s.encoder_hit_by_impl   = toVec(e_hit());
    return s;
}

} } // namespace va::core
