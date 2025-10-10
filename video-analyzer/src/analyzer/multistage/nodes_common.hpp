#pragma once

#include <unordered_map>
#include <string>

namespace va { namespace analyzer { namespace multistage { namespace util {

inline std::string get_or(const std::unordered_map<std::string,std::string>& m,
                          const std::string& key, const std::string& defv) {
    auto it = m.find(key); return it==m.end()? defv : it->second;
}

inline int get_or_int(const std::unordered_map<std::string,std::string>& m,
                      const std::string& key, int defv) {
    auto it = m.find(key); if (it==m.end()) return defv; try { return std::stoi(it->second); } catch (...) { return defv; }
}

inline float get_or_float(const std::unordered_map<std::string,std::string>& m,
                          const std::string& key, float defv) {
    auto it = m.find(key); if (it==m.end()) return defv; try { return std::stof(it->second); } catch (...) { return defv; }
}

} } } } // namespace

