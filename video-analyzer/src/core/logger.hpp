#pragma once

#include "ConfigLoader.hpp"

#include <chrono>
#include <fstream>
#include <atomic>
#include <memory>
#include <mutex>
#include <optional>
#include <ostream>
#include <sstream>
#include <streambuf>
#include <string>
#include <unordered_map>

namespace va::core {

enum class LogLevel {
    Trace = 0,
    Debug,
    Info,
    Warn,
    Error
};

enum class LogFormat {
    Text = 0,
    Json = 1,
};

class Logger {
public:
    class Stream {
    public:
        Stream(Logger& logger, LogLevel level, const char* component = nullptr);
        Stream(Stream&& other) noexcept;
        ~Stream();

        template <typename T>
        Stream& operator<<(const T& value) {
            buffer_ << value;
            return *this;
        }

        Stream& operator<<(std::ostream& (*manip)(std::ostream&));

    private:
        Logger* logger_ {nullptr};
        LogLevel level_ {LogLevel::Info};
        const char* component_ {"app"};
        std::ostringstream buffer_;
        bool moved_ {false};
    };

    static Logger& instance();

    void configure(const ObservabilityConfig& config);
    Stream stream(LogLevel level, const char* component = nullptr);

    bool isEnabled(LogLevel level) const;
    bool isEnabled(LogLevel level, const char* component) const;

    // Module level control via env/REST
    void setModuleLevel(const std::string& component, LogLevel level);
    void setFormat(LogFormat fmt);

private:
    Logger() = default;

    void log(LogLevel level, const char* component, const std::string& message);
    std::string levelToString(LogLevel level) const;
    std::string timestamp() const;
    void openLogFile();
    void rotateIfNeeded(size_t incoming_bytes);
    LogLevel parseLevel(const std::string& level) const;
    void installRedirects();
    void parseModuleLevelsEnv();
    void parseFormatEnv();

    mutable std::mutex mutex_;
    LogLevel level_threshold_ {LogLevel::Info};
    bool console_enabled_ {true};
    std::string file_path_;
    size_t file_max_size_bytes_ {0};
    int file_max_files_ {0};
    std::ofstream file_stream_;
    LogFormat format_ {LogFormat::Text};
    std::unordered_map<std::string, LogLevel> module_levels_;

    class StreambufRedirect;
    std::unique_ptr<StreambufRedirect> cout_redirect_;
    std::unique_ptr<StreambufRedirect> cerr_redirect_;
    std::streambuf* original_cout_ {nullptr};
    std::streambuf* original_cerr_ {nullptr};
    bool redirects_installed_ {false};
};

} // namespace va::core

#define VA_LOG_STREAM(level) ::va::core::Logger::instance().stream(level, "app")
#define VA_LOG_C(level, component) ::va::core::Logger::instance().stream(level, component)
#define VA_LOG_TRACE() VA_LOG_STREAM(::va::core::LogLevel::Trace)
#define VA_LOG_DEBUG() VA_LOG_STREAM(::va::core::LogLevel::Debug)
#define VA_LOG_INFO()  VA_LOG_STREAM(::va::core::LogLevel::Info)
#define VA_LOG_WARN()  VA_LOG_STREAM(::va::core::LogLevel::Warn)
#define VA_LOG_ERROR() VA_LOG_STREAM(::va::core::LogLevel::Error)

// Throttled / Every-N logging helpers (single-statement usage)
#define VA_LOG_EVERY_N(level, component, N) \
    for (static std::atomic<uint64_t> _va_cnt{0}; ((_va_cnt.fetch_add(1, std::memory_order_relaxed) % (uint64_t)(N)) == 0); ) \
        VA_LOG_C(level, component)

#define VA_LOG_ONCE(component) \
    for (static std::atomic<bool> _va_once{false}; (!_va_once.exchange(true, std::memory_order_acq_rel)); ) \
        VA_LOG_C(::va::core::LogLevel::Info, component)

#define VA_LOG_THROTTLED(level, component, PERIOD_MS) \
    for (static std::atomic<long long> _va_last_ms{0}; ([&]() { \
            const auto _now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count(); \
            auto _prev = _va_last_ms.load(std::memory_order_relaxed); \
            if (_now_ms - _prev >= (long long)(PERIOD_MS) && _va_last_ms.compare_exchange_strong(_prev, _now_ms)) return true; \
            return false; })(); ) \
        VA_LOG_C(level, component)

