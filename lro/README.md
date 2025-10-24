# LRO (Long-Running Operation) Library

A small, header-first C++ library for modeling and running long-running operations (LRO):
status machine, execution pipeline, per-bucket admission control, fair scheduling,
merge/idempotency, backpressure (Retry-After estimation), notifier hooks, and metrics snapshots.

## Build (as subdirectory)

```
add_subdirectory(lro)
target_link_libraries(your_target PRIVATE lro::lro)
```

## Minimum C++ API (header-first)

- include/lro/runner.hpp – Runner/Operation/Step/RunnerConfig
- include/lro/state_store.hpp – IStateStore/MemoryStore/WalStoreAdapter (interfaces)
- include/lro/admission.hpp – AdmissionPolicy (multi-bucket + fair window)
- include/lro/metrics.hpp – Metrics snapshot types
- include/lro/notifier.hpp – INotifier (SSE/WS/Webhook hooks)
- include/lro/reason.hpp – normalizeReason hook

Adapters (optional):
- include/lro/adapters/rest_simple.hpp – helper for REST wiring
- include/lro/adapters/wal.hpp – WAL adapter interface

This repository intentionally ships header-only skeletons to keep integration simple.
Move logic into src/ and flip `LRO_HEADER_ONLY=OFF` when you need compiled objects.

