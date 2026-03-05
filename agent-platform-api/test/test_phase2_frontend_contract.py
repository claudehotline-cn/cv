from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_frontend_routes_include_cache_metrics() -> None:
    src = (_repo_root() / 'agent-chat-vue/src/router.ts').read_text(encoding='utf-8')
    assert "path: 'cache-metrics'" in src
    assert "name: 'SettingsCacheMetrics'" in src
    assert 'CacheMetricsView.vue' in src
