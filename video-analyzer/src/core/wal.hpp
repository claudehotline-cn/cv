#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace va::core::wal {

// 最小可用：将订阅状态变更以 JSON 行写入本地 WAL 文件，默认关闭；
// 通过环境变量 VA_WAL_SUBSCRIPTIONS=1 启用。文件路径：logs/subscriptions.wal

bool enabled();
void init();

// 追加一条订阅事件
// op: enqueue | ready | failed | cancelled | restart
void append_subscription_event(const std::string& op,
                               const std::string& sub_id,
                               const std::string& base_key, // stream_id:profile_id
                               const std::string& phase,
                               const std::string& reason_code,
                               std::uint64_t ts_pending,
                               std::uint64_t ts_preparing,
                               std::uint64_t ts_opening,
                               std::uint64_t ts_loading,
                               std::uint64_t ts_starting,
                               std::uint64_t ts_ready,
                               std::uint64_t ts_failed,
                               std::uint64_t ts_cancelled);

// 进程重启标记（用于线下取证）：写入一条 restart 事件
void mark_restart();

// 扫描 WAL：统计上次重启前未到终态的订阅（近似按 base_key 聚合）
void scanInflightBeforeLastRestart();

// 读取最近一次扫描得到的 failed(restart) 计数
std::uint64_t failedRestartCount();

// 读取 WAL 尾部 n 行（仅当前活动文件，最小充分取证）
std::vector<std::string> tail(std::size_t n);

} // namespace va::core::wal
