# Repository Guidelines

This document is a concise contributor guide for this repository. It explains how the codebase is organized and how to build, test, and contribute efficiently.

## Project Structure & Module Organization
- `video-analyzer/` – Core backend (RTSP ingest, preprocessing, inference, post‑processing, WebRTC/HLS output).
- `web-frontend/` – Web UI to preview streams and overlays.
- `video-source-manager/` – Utilities for managing RTSP sources.
- `docs/` – Design notes, GPU 全链路改造方案与规划, testing guides.
- `tools/` – Dev scripts (build/run, test helpers).
- `third_party/` – External deps or vendored code.

## Build, Test, and Development Commands
- Build (CMake, out-of-tree):
  - Windows: `tools\build.ps1 -Config Release` or `cmake -S . -B build && cmake --build build --config Release`
  - Linux/macOS: `cmake -S . -B build && cmake --build build -j`
- Run backend: `build/video-analyzer/VideoAnalyzer` (Windows: select config subfolder).
- Run tests: 使用d:\Projects\ai\cv\video-analyzer\test\scripts下的脚本测试
- Common targets: `VideoAnalyzer`, `install`, `package` (if defined).

## Coding Style & Naming Conventions
- C++: follow existing style (brace on same line, 2–4 spaces; prefer `snake_case` for functions/files, `CamelCase` for classes).
- Avoid one-letter identifiers; keep methods short and focused.
- Use `const`, `span`, and `string_view` where appropriate; prefer `unique_ptr`/`shared_ptr` over raw ownership.
- Formatting: keep consistent with surrounding files; do not add license headers unless asked.

## Testing Guidelines
- Python tests live in `video-analyzer/test/`. Add new cases alongside existing scripts.
- Name scripts descriptively, e.g., `check_gpu_inference.py`, `compare_modes.py`.
- Minimum: verify frames are processed (>0) and no HTTP/RTSP errors. Prefer adding assertions for FPS and detection counts.

## Commit & Pull Request Guidelines
- Commits: use imperative present tense, e.g., "Implement GPU IoBinding host staging".
- Group related changes; keep diffs focused. Reference issues with `#id` when applicable.
- Pull Requests: include summary, motivation, key changes, testing evidence (logs/screenshots), and rollback plan.

## Agent-Specific Notes
- Respect staged plans; prefer minimal, targeted patches.
- Do not change public interfaces unless the plan/owner confirms.
- When adding GPU paths, keep CPU fallback intact; guard features behind options and verify via automated tests before merging.

