# Prometheus Alerts for Video Analyzer (M2)

- Import `docs/references/alerts/va_alerts.yaml` into your Prometheus alerting config.
- Suggested alerts (tunable):
  - `VAQuotaDropSpike`: sum(rate(va_quota_dropped_total[5m])) > 0.5 for 2m
  - `VAQuotaWouldDropHigh`: sum(rate(va_quota_would_drop_total[5m])) > 2 for 3m
  - `VAQuotaEnforcePercentLow`: avg(va_quota_enforce_percent) < 50 for 5m
  - `VASubscriptionFailuresElevated`: sum(rate(va_subscriptions_failed_by_reason_total[5m])) > 0.2 for 3m

Tips:
- First land on Grafana quota panels (dropped/would-drop + enforce%) to correlate with traffic.
- If observe-only is enabled, expect `would_drop` > 0 while `dropped` ~ 0.
- Use per-key overrides to canary enforcement (override.enforce_percent) or disable (override.observe_only).
