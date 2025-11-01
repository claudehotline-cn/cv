#pragma once

#include <sstream>
#include <cstdint>
#include <string>
#include <unordered_set>

namespace va::core {

// Minimal Prometheus text exposition builder (0.0.4)
class MetricsTextBuilder {
public:
    void header(const std::string& name, const std::string& type, const std::string& help) {
        const std::string key = name + "|" + type;
        if (emitted_.insert(key).second) {
            if (!help.empty()) {
                out_ << "# HELP " << name << ' ' << help << "\n";
            }
            out_ << "# TYPE " << name << ' ' << type << "\n";
        }
    }

    void sample(const std::string& name, const std::string& label_str, const std::string& value) {
        out_ << name << label_str << ' ' << value << "\n";
    }
    void sample(const std::string& name, const std::string& label_str, uint64_t value) {
        out_ << name << label_str << ' ' << static_cast<unsigned long long>(value) << "\n";
    }
    void sample(const std::string& name, const std::string& label_str, double value) {
        out_ << name << label_str << ' ' << value << "\n";
    }

    std::string str() const { return out_.str(); }

private:
    std::ostringstream out_;
    std::unordered_set<std::string> emitted_;
};

} // namespace va::core

