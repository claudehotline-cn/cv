## VA 仓库控制 CLI（P1）

提供最小仓库控制（In‑Process Triton）：`load/unload/poll`。

- 可执行：`controlplane/build/va_repo`
- 用法：

```
va_repo --va-addr <host:port> load   <model>
va_repo --va-addr <host:port> unload <model>
va_repo --va-addr <host:port> poll
```

说明：
- 仅当 VA 以 In‑Process Triton 嵌入方式运行且启用 `triton_repo` 时有效；
- `load/unload` 依赖 `model_control=explicit`；`poll` 触发仓库轮询。

