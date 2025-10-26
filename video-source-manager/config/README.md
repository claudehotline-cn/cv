该目录用于放置 VSM 运行期配置（将来可扩展 TLS 配置）。
当前版本：VSM 默认开启 TLS 并使用 controlplane/config/certs 下的证书，无需环境变量。
如需自定义证书路径，可设置环境变量 VSM_TLS_CA/VSM_TLS_CERT/VSM_TLS_KEY（兼容保留），或后续合入 YAML 解析支持。
