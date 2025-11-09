## 发布手册（P9）

目标：以最小步骤完成模型上线、压测调优、回滚/降级。

准备
- VA 引擎：`provider=triton`、`triton_inproc=true`、`triton_repo` 指向 MinIO 仓库。
- Controlplane 构建产物：`va_release`、`va_repo`、`va_set_engine`。

上线（Ensemble 建议）
1. 上传子模型与 Ensemble 目录（参考 `docs/examples/triton/ensembles`）。
2. 可选预加载：`va_repo --va-addr <va> load <model>`。
3. 切换：
```
controlplane/build/va_release --va-addr <va> --pipeline det --node model --triton-model <model> [--triton-version <ver>]
```
4. Smoke：`tools/validate/e2e_smoke.sh --cp http://<cp>`。

压测与调优
- 开端口：`triton_enable_grpc: true`。
- 运行 perf 与推荐：见 `docs/examples/triton/perf_guide.md`。
- 更新 `config.pbtxt` 后复测。

回滚/降级
- 回滚版本：`tools/release/va_restore_triton.sh --va-addr <va> --model <ens_*|model> [--version <N>]`
- 降级 provider（CUDA）：`tools/release/va_fallback.sh --va-addr <va> [--device <id>]`

观测与排障
- Controlplane 指标：`GET /api/_metrics/summary`、`/metrics`
- VA 运行态：`GET /api/va/runtime`
- 仓库操作：`va_repo load|unload|poll`

