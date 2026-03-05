from pathlib import Path


def test_phase2_composition_root_builds_container() -> None:
    from app.composition_root import Phase2Container, build_phase2_container
    from app.platform_core.orchestrator import execute

    container = build_phase2_container()

    assert isinstance(container, Phase2Container)
    assert container.orchestrator is execute
    assert container.guardrails is not None
    assert container.semantic_cache is not None
    assert container.telemetry is not None


def test_main_wires_phase2_container_on_startup_contract() -> None:
    main_file = Path(__file__).resolve().parents[1] / "app" / "main.py"
    source = main_file.read_text(encoding="utf-8")

    assert "from app.composition_root import build_phase2_container" in source
    assert "app.state.phase2 = build_phase2_container()" in source
