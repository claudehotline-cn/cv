import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import HTTPException


async def _ok_executor(_ctx):
    return {"ok": True}


class _GuardrailDecision:
    def __init__(
        self,
        *,
        action: str = "allow",
        reason_code: str | None = None,
        payload: dict[str, object] | None = None,
        sanitized_text: str | None = None,
    ) -> None:
        self.action = action
        self.reason_code = reason_code
        self.payload = payload
        self.sanitized_text = sanitized_text


class _FakeGuardrails:
    def __init__(
        self,
        *,
        input_decision: _GuardrailDecision | None = None,
        output_decision: _GuardrailDecision | None = None,
    ) -> None:
        self.calls: list[tuple[str, str | None, str]] = []
        self._input_decision = input_decision or _GuardrailDecision(action="allow")
        self._output_decision = output_decision or _GuardrailDecision(action="allow")

    async def evaluate_input(
        self,
        *,
        tenant_id: str | None,
        text: str,
        request_id: str | None = None,
    ) -> _GuardrailDecision:
        _ = request_id
        self.calls.append(("input", tenant_id, text))
        return self._input_decision

    async def evaluate_output(
        self,
        *,
        tenant_id: str | None,
        text: str,
        request_id: str | None = None,
    ) -> _GuardrailDecision:
        _ = request_id
        self.calls.append(("output", tenant_id, text))
        return self._output_decision


def _fake_request_with_phase2(
    orchestrator,
    *,
    telemetry=None,
    guardrails=None,
    semantic_cache=None,
):
    phase2 = SimpleNamespace(
        orchestrator=orchestrator,
        telemetry=telemetry or object(),
        guardrails=guardrails or _FakeGuardrails(),
        semantic_cache=semantic_cache or object(),
    )
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(phase2=phase2)))


@pytest.fixture
def routes_modules(monkeypatch):
    fake_registry = ModuleType("app.core.agent_registry")
    fake_registry.registry = SimpleNamespace(get_plugin=lambda _key: None)
    monkeypatch.setitem(sys.modules, "app.core.agent_registry", fake_registry)

    fake_auth = ModuleType("app.core.auth")

    class _AuthPrincipal:
        def __init__(self, user_id="u", role="user", tenant_id=None, tenant_role=None):
            self.user_id = user_id
            self.role = role
            self.tenant_id = tenant_id
            self.tenant_role = tenant_role

    async def _get_current_user():
        return _AuthPrincipal()

    fake_auth.AuthPrincipal = _AuthPrincipal
    fake_auth.get_current_user = _get_current_user
    monkeypatch.setitem(sys.modules, "app.core.auth", fake_auth)

    fake_governance = ModuleType("app.core.governance")
    fake_governance.GovernanceKeys = lambda **kwargs: kwargs

    async def _enforce_rate_limit(*_args, **_kwargs):
        return None

    async def _acquire_execute_concurrency(*_args, **_kwargs):
        return True, "tenant"

    async def _release_execute_concurrency(*_args, **_kwargs):
        return None

    fake_governance.enforce_rate_limit = _enforce_rate_limit
    fake_governance.acquire_execute_concurrency = _acquire_execute_concurrency
    fake_governance.release_execute_concurrency = _release_execute_concurrency
    monkeypatch.setitem(sys.modules, "app.core.governance", fake_governance)

    fake_quota_service = ModuleType("app.services.quota_service")

    class _QuotaService:
        def __init__(self, _db):
            pass

        async def check_quota_or_raise(self, _tenant_id):
            return None

        async def get_effective_execute_policy(self, _tenant_id):
            return {
                "tenant_execute_limit": "60/min",
                "user_execute_limit": "20/min",
                "tenant_concurrency_limit": 10,
                "user_concurrency_limit": 5,
            }

        async def get_effective_rw_policy(self, _tenant_id, _bucket):
            return {"tenant_limit": "120/min", "user_limit": "60/min"}

    fake_quota_service.QuotaService = _QuotaService
    monkeypatch.setitem(sys.modules, "app.services.quota_service", fake_quota_service)

    fake_secrets_service = ModuleType("app.services.secrets_service")

    class _SecretsService:
        def __init__(self, _db):
            pass

    fake_secrets_service.SecretsService = _SecretsService
    monkeypatch.setitem(sys.modules, "app.services.secrets_service", fake_secrets_service)

    fake_secrets_injector = ModuleType("app.services.secrets_injector")

    class _RuntimeSecretInjector:
        def __init__(self, _service):
            pass

        async def resolve(self, **_kwargs):
            return []

        def inject(self, runtime_config, resolved):
            _ = resolved
            return runtime_config

    fake_secrets_injector.RuntimeSecretInjector = _RuntimeSecretInjector
    monkeypatch.setitem(sys.modules, "app.services.secrets_injector", fake_secrets_injector)

    import fastapi.dependencies.utils as fastapi_utils
    monkeypatch.setattr(fastapi_utils, "ensure_multipart_is_installed", lambda: None)

    for mod in ("app.routes.chat", "app.routes.rag", "app.routes.tasks"):
        sys.modules.pop(mod, None)

    chat_routes = importlib.import_module("app.routes.chat")
    rag_routes = importlib.import_module("app.routes.rag")
    task_routes = importlib.import_module("app.routes.tasks")
    return chat_routes, rag_routes, task_routes


@pytest.fixture
def worker_module(monkeypatch):
    fake_agent_core_settings = ModuleType("agent_core.settings")

    class _FakeSettings:
        redis_url = "redis://example"

    fake_agent_core_settings.get_settings = lambda: _FakeSettings()
    monkeypatch.setitem(sys.modules, "agent_core.settings", fake_agent_core_settings)

    fake_composition_root = ModuleType("app.composition_root")
    fake_composition_root.build_phase2_container = lambda: SimpleNamespace(
        orchestrator=lambda *_args, **_kwargs: None,
        telemetry=object(),
        semantic_cache=object(),
        guardrails=_FakeGuardrails(),
    )
    monkeypatch.setitem(sys.modules, "app.composition_root", fake_composition_root)

    fake_governance = ModuleType("app.core.governance")
    fake_governance.GovernanceKeys = lambda **kwargs: kwargs

    async def _release_execute_concurrency(*_args, **_kwargs):
        return None

    fake_governance.release_execute_concurrency = _release_execute_concurrency
    monkeypatch.setitem(sys.modules, "app.core.governance", fake_governance)

    fake_interrupts = ModuleType("app.utils.interrupts")
    fake_interrupts.extract_interrupt_data = lambda _state: None
    monkeypatch.setitem(sys.modules, "app.utils.interrupts", fake_interrupts)

    fake_session_memory = ModuleType("app.utils.session_memory")
    fake_session_memory.format_recent_messages_for_prompt = lambda _messages: ""
    monkeypatch.setitem(sys.modules, "app.utils.session_memory", fake_session_memory)

    fake_arq = ModuleType("arq")
    fake_arq.ArqRedis = object
    monkeypatch.setitem(sys.modules, "arq", fake_arq)

    fake_arq_connections = ModuleType("arq.connections")

    class _RedisSettings:
        @classmethod
        def from_dsn(cls, _dsn):
            return cls()

    fake_arq_connections.RedisSettings = _RedisSettings
    monkeypatch.setitem(sys.modules, "arq.connections", fake_arq_connections)

    sys.modules.pop("app.worker", None)
    return importlib.import_module("app.worker")


@pytest.mark.asyncio
async def test_chat_wrapper_returns_payload_when_orchestrator_ok(routes_modules) -> None:
    chat_routes, _rag_routes, _task_routes = routes_modules
    calls = {"executor": 0}
    fake_guardrails = _FakeGuardrails()
    fake_cache = object()
    captured: dict[str, object] = {}

    async def _executor(_ctx):
        calls["executor"] += 1
        return {"graph": "g", "config": {"k": "v"}}

    async def _orchestrator(request, ctx, executor):
        captured["request"] = request
        captured["ctx"] = ctx
        payload = await executor(ctx)
        return {"status": "ok", "reason_code": None, "payload": payload}

    payload = await chat_routes._run_with_phase2_orchestrator(
        orchestrator=_orchestrator,
        telemetry=object(),
        guardrails=fake_guardrails,
        semantic_cache=fake_cache,
        tenant_id="tenant-1",
        namespace="chat.stream",
        model_key="data_agent",
        query_text="hello",
        executor=_executor,
    )

    assert payload == {"graph": "g", "config": {"k": "v"}}
    assert calls["executor"] == 1

    ctx = captured["ctx"]
    request = captured["request"]
    assert getattr(ctx, "semantic_cache") is fake_cache
    pre_input_check = getattr(ctx, "pre_input_check")
    post_output_check = getattr(ctx, "post_output_check")
    assert callable(pre_input_check)
    assert callable(post_output_check)

    pre_decision = await pre_input_check(request, ctx)
    post_decision = await post_output_check(request, payload, ctx)
    assert pre_decision.action == "allow"
    assert post_decision.action == "allow"
    assert fake_guardrails.calls == [
        ("input", "tenant-1", "hello"),
        ("output", "tenant-1", "{'graph': 'g', 'config': {'k': 'v'}}"),
    ]


@pytest.mark.asyncio
async def test_chat_wrapper_maps_redact_to_sanitized_payload(routes_modules) -> None:
    chat_routes, _rag_routes, _task_routes = routes_modules
    fake_guardrails = _FakeGuardrails(
        output_decision=_GuardrailDecision(
            action="redact",
            reason_code="output_pii_redact",
            payload={"pii": True},
            sanitized_text="SANITIZED",
        )
    )

    async def _executor(_ctx):
        return {"answer": "sensitive text"}

    captured: dict[str, object] = {}

    async def _orchestrator(request, ctx, executor):
        payload = await executor(ctx)
        decision = await ctx.post_output_check(request, payload, ctx)
        captured["sanitized_payload"] = getattr(decision, "sanitized_payload", None)
        return {
            "status": "ok",
            "reason_code": decision.reason_code,
            "payload": payload,
        }

    await chat_routes._run_with_phase2_orchestrator(
        orchestrator=_orchestrator,
        telemetry=object(),
        guardrails=fake_guardrails,
        semantic_cache=object(),
        tenant_id="tenant-1",
        namespace="chat.stream",
        model_key="data_agent",
        query_text="hello",
        executor=_executor,
    )

    assert captured["sanitized_payload"] == {"answer": "SANITIZED"}


@pytest.mark.asyncio
async def test_chat_session_query_must_include_tenant_scope() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app/routes/chat.py").read_text(encoding="utf-8")

    assert "SessionModel.tenant_id" in source


@pytest.mark.asyncio
async def test_tasks_wrapper_raises_403_when_orchestrator_blocked(routes_modules) -> None:
    _chat_routes, _rag_routes, task_routes = routes_modules

    async def _orchestrator(_request, _ctx, _executor):
        return {
            "status": "blocked",
            "reason_code": "policy_input_block",
            "payload": {"blocked": True},
        }

    req = _fake_request_with_phase2(_orchestrator)
    user = SimpleNamespace(tenant_id="tenant-1")

    with pytest.raises(HTTPException) as exc:
        await task_routes._run_with_phase2_orchestrator(
            req=req,
            user=user,
            namespace="tasks.execute",
            model_key="data_agent",
            query_text="dangerous input",
            executor=_ok_executor,
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == {
        "detail": "orchestrator_blocked",
        "reason_code": "policy_input_block",
    }


@pytest.mark.asyncio
async def test_tasks_wrapper_wires_phase2_guardrails_and_cache_into_context(routes_modules) -> None:
    _chat_routes, _rag_routes, task_routes = routes_modules
    fake_guardrails = _FakeGuardrails()
    fake_cache = object()
    captured: dict[str, object] = {}

    async def _orchestrator(request, ctx, executor):
        captured["request"] = request
        captured["ctx"] = ctx
        payload = await executor(ctx)
        return {"status": "ok", "reason_code": None, "payload": payload}

    req = _fake_request_with_phase2(_orchestrator, guardrails=fake_guardrails, semantic_cache=fake_cache)
    user = SimpleNamespace(tenant_id="tenant-1")

    payload = await task_routes._run_with_phase2_orchestrator(
        req=req,
        user=user,
        namespace="tasks.execute",
        model_key="data_agent",
        query_text="safe input",
        executor=_ok_executor,
    )

    assert payload == {"ok": True}

    ctx = captured["ctx"]
    request = captured["request"]
    assert getattr(ctx, "semantic_cache") is fake_cache
    pre_input_check = getattr(ctx, "pre_input_check")
    post_output_check = getattr(ctx, "post_output_check")
    assert callable(pre_input_check)
    assert callable(post_output_check)

    pre_decision = await pre_input_check(request, ctx)
    post_decision = await post_output_check(request, payload, ctx)
    assert pre_decision.action == "allow"
    assert post_decision.action == "allow"
    assert fake_guardrails.calls == [
        ("input", "tenant-1", "safe input"),
        ("output", "tenant-1", "{'ok': True}"),
    ]


@pytest.mark.asyncio
async def test_rag_wrapper_raises_403_when_orchestrator_blocked(routes_modules, monkeypatch) -> None:
    _chat_routes, rag_routes, _task_routes = routes_modules

    async def _orchestrator(_request, _ctx, _executor):
        return {
            "status": "blocked",
            "reason_code": "policy_output_block",
            "payload": {"blocked": True},
        }

    monkeypatch.setattr(rag_routes, "_dev_user_ctx", lambda _req: {"tenant_id": "tenant-1"})
    req = _fake_request_with_phase2(_orchestrator)

    with pytest.raises(HTTPException) as exc:
        await rag_routes._run_with_phase2_orchestrator(
            req=req,
            namespace="rag.proxy",
            model_key="POST:/api/retrieve",
            query_text="blocked",
            executor=_ok_executor,
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == {
        "detail": "orchestrator_blocked",
        "reason_code": "policy_output_block",
    }


@pytest.mark.asyncio
async def test_rag_wrapper_wires_phase2_guardrails_and_cache_into_context(routes_modules, monkeypatch) -> None:
    _chat_routes, rag_routes, _task_routes = routes_modules
    fake_guardrails = _FakeGuardrails()
    fake_cache = object()
    captured: dict[str, object] = {}

    async def _orchestrator(request, ctx, executor):
        captured["request"] = request
        captured["ctx"] = ctx
        payload = await executor(ctx)
        return {"status": "ok", "reason_code": None, "payload": payload}

    monkeypatch.setattr(rag_routes, "_dev_user_ctx", lambda _req: {"tenant_id": "tenant-1"})
    req = _fake_request_with_phase2(_orchestrator, guardrails=fake_guardrails, semantic_cache=fake_cache)

    payload = await rag_routes._run_with_phase2_orchestrator(
        req=req,
        namespace="rag.proxy",
        model_key="POST:/api/retrieve",
        query_text='{"q":"hello"}',
        executor=_ok_executor,
    )

    assert payload == {"ok": True}

    ctx = captured["ctx"]
    request = captured["request"]
    assert getattr(ctx, "semantic_cache") is fake_cache
    pre_input_check = getattr(ctx, "pre_input_check")
    post_output_check = getattr(ctx, "post_output_check")
    assert callable(pre_input_check)
    assert callable(post_output_check)

    pre_decision = await pre_input_check(request, ctx)
    post_decision = await post_output_check(request, payload, ctx)
    assert pre_decision.action == "allow"
    assert post_decision.action == "allow"
    assert fake_guardrails.calls == [
        ("input", "tenant-1", '{"q":"hello"}'),
        ("output", "tenant-1", "{'ok': True}"),
    ]


@pytest.mark.asyncio
async def test_rag_upload_document_routes_through_phase2_wrapper(routes_modules, monkeypatch) -> None:
    _chat_routes, rag_routes, _task_routes = routes_modules
    calls = {"wrapper": 0, "multipart": 0}
    captured: dict[str, object] = {}

    async def _wrapper(*, req, namespace, model_key, query_text, executor):
        calls["wrapper"] += 1
        captured["namespace"] = namespace
        captured["model_key"] = model_key
        captured["query_text"] = query_text
        _ = req
        return await executor(None)

    async def _multipart(*, path, req, request_id, file):
        calls["multipart"] += 1
        _ = req
        _ = request_id
        return {"ok": True, "path": path, "filename": file.filename}

    async def _emit_audit(**_kwargs):
        return None

    monkeypatch.setattr(rag_routes, "_run_with_phase2_orchestrator", _wrapper)
    monkeypatch.setattr(rag_routes, "_proxy_multipart", _multipart)
    monkeypatch.setattr(rag_routes, "_emit_audit", _emit_audit)
    monkeypatch.setattr(
        rag_routes,
        "_dev_user_ctx",
        lambda _req: {
            "user_id": "u",
            "role": "admin",
            "tenant_id": "tenant-1",
            "tenant_role": "owner",
        },
    )

    req = SimpleNamespace(headers={}, app=SimpleNamespace(state=SimpleNamespace(event_bus=SimpleNamespace(redis=object()))))
    fake_file = SimpleNamespace(filename="sample.txt")

    out = await rag_routes.upload_document(req=req, kb_id=42, file=fake_file)

    assert calls["wrapper"] == 1
    assert calls["multipart"] == 1
    assert captured["namespace"] == "rag.proxy"
    assert captured["model_key"] == "POST:/api/knowledge-bases/42/documents/upload"
    assert out == {
        "ok": True,
        "path": "/api/knowledge-bases/42/documents/upload",
        "filename": "sample.txt",
        "request_id": out["request_id"],
    }
    assert isinstance(out["request_id"], str)


@pytest.mark.asyncio
async def test_chat_wrapper_uses_noop_telemetry_when_missing(routes_modules) -> None:
    from app.platform_core.orchestrator import execute as _execute

    chat_routes, _rag_routes, _task_routes = routes_modules

    async def _executor(_ctx):
        return {"ok": True}

    payload = await chat_routes._run_with_phase2_orchestrator(
        orchestrator=_execute,
        telemetry=None,
        guardrails=None,
        semantic_cache=None,
        tenant_id="tenant-1",
        namespace="chat.stream",
        model_key="data_agent",
        query_text="hello",
        executor=_executor,
    )

    assert payload == {"ok": True}


@pytest.mark.asyncio
async def test_tasks_wrapper_uses_noop_telemetry_when_missing(routes_modules) -> None:
    from app.platform_core.orchestrator import execute as _execute

    _chat_routes, _rag_routes, task_routes = routes_modules
    req = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                phase2=SimpleNamespace(
                    orchestrator=_execute,
                    telemetry=None,
                    guardrails=None,
                    semantic_cache=None,
                )
            )
        )
    )
    user = SimpleNamespace(tenant_id="tenant-1")

    payload = await task_routes._run_with_phase2_orchestrator(
        req=req,
        user=user,
        namespace="tasks.execute",
        model_key="data_agent",
        query_text="safe input",
        executor=_ok_executor,
    )

    assert payload == {"ok": True}


@pytest.mark.asyncio
async def test_rag_wrapper_uses_noop_telemetry_when_missing(routes_modules, monkeypatch) -> None:
    from app.platform_core.orchestrator import execute as _execute

    _chat_routes, rag_routes, _task_routes = routes_modules
    req = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                phase2=SimpleNamespace(
                    orchestrator=_execute,
                    telemetry=None,
                    guardrails=None,
                    semantic_cache=None,
                )
            )
        ),
        headers={},
    )
    monkeypatch.setattr(rag_routes, "_dev_user_ctx", lambda _req: {"tenant_id": "tenant-1"})

    payload = await rag_routes._run_with_phase2_orchestrator(
        req=req,
        namespace="rag.proxy",
        model_key="POST:/api/retrieve",
        query_text='{"q":"hello"}',
        executor=_ok_executor,
    )

    assert payload == {"ok": True}


@pytest.mark.asyncio
async def test_rag_proxy_json_prefers_sanitized_content_over_raw(routes_modules, monkeypatch) -> None:
    _chat_routes, rag_routes, _task_routes = routes_modules

    async def _wrapper(*, req, namespace, model_key, query_text, executor):
        _ = (req, namespace, model_key, query_text, executor)
        return {"__raw__": {"answer": "raw-sensitive"}, "content": "SANITIZED"}

    monkeypatch.setattr(rag_routes, "_run_with_phase2_orchestrator", _wrapper)

    req = SimpleNamespace(headers={}, app=SimpleNamespace(state=SimpleNamespace()))
    out = await rag_routes._proxy_json(
        method="POST",
        path="/api/retrieve",
        req=req,
        json_body={"q": "hello"},
    )

    assert out == {"content": "SANITIZED"}


@pytest.mark.asyncio
async def test_rag_upload_document_prefers_sanitized_content_over_raw(routes_modules, monkeypatch) -> None:
    _chat_routes, rag_routes, _task_routes = routes_modules

    async def _wrapper(*, req, namespace, model_key, query_text, executor):
        _ = (req, namespace, model_key, query_text, executor)
        return {
            "__raw__": {"answer": "raw-sensitive"},
            "content": "SANITIZED",
        }

    async def _emit_audit(**_kwargs):
        return None

    monkeypatch.setattr(rag_routes, "_run_with_phase2_orchestrator", _wrapper)
    monkeypatch.setattr(rag_routes, "_emit_audit", _emit_audit)
    monkeypatch.setattr(
        rag_routes,
        "_dev_user_ctx",
        lambda _req: {
            "user_id": "u",
            "role": "admin",
            "tenant_id": "tenant-1",
            "tenant_role": "owner",
        },
    )

    req = SimpleNamespace(headers={}, app=SimpleNamespace(state=SimpleNamespace(event_bus=SimpleNamespace(redis=object()))))
    fake_file = SimpleNamespace(filename="sample.txt")

    out = await rag_routes.upload_document(req=req, kb_id=42, file=fake_file)

    assert out == {
        "content": "SANITIZED",
        "request_id": out["request_id"],
    }
    assert isinstance(out["request_id"], str)


@pytest.mark.asyncio
async def test_worker_wrapper_wires_phase2_guardrails_and_cache_into_context(worker_module, monkeypatch) -> None:
    worker = worker_module
    fake_guardrails = _FakeGuardrails()
    fake_cache = object()
    captured: dict[str, object] = {}

    async def _executor(_ctx):
        return {"cancelled": False}

    async def _orchestrator(request, ctx, executor):
        captured["request"] = request
        captured["ctx"] = ctx
        payload = await executor(ctx)
        return {"status": "ok", "reason_code": None, "payload": payload}

    monkeypatch.setattr(worker, "phase2", SimpleNamespace(orchestrator=_orchestrator))
    monkeypatch.setattr(
        worker,
        "_phase2_container",
        SimpleNamespace(telemetry=object(), semantic_cache=fake_cache, guardrails=fake_guardrails),
    )

    payload = await worker._run_with_phase2_orchestrator(
        tenant_id="tenant-1",
        namespace="worker.execute",
        model_key="data_agent",
        query_text="ok",
        executor=_executor,
    )

    assert payload == {"cancelled": False}

    ctx = captured["ctx"]
    request = captured["request"]
    assert getattr(ctx, "semantic_cache") is fake_cache
    pre_input_check = getattr(ctx, "pre_input_check")
    post_output_check = getattr(ctx, "post_output_check")
    assert callable(pre_input_check)
    assert callable(post_output_check)

    pre_decision = await pre_input_check(request, ctx)
    post_decision = await post_output_check(request, payload, ctx)
    assert pre_decision.action == "allow"
    assert post_decision.action == "allow"
    assert fake_guardrails.calls == [
        ("input", "tenant-1", "ok"),
        ("output", "tenant-1", "{'cancelled': False}"),
    ]


@pytest.mark.asyncio
async def test_worker_wrapper_raises_runtime_error_when_orchestrator_blocked(worker_module, monkeypatch) -> None:
    worker = worker_module

    async def _orchestrator(_request, _ctx, _executor):
        return {
            "status": "blocked",
            "reason_code": "policy_input_block",
            "payload": {"blocked": True},
        }

    monkeypatch.setattr(worker, "phase2", SimpleNamespace(orchestrator=_orchestrator))
    monkeypatch.setattr(
        worker,
        "_phase2_container",
        SimpleNamespace(telemetry=object(), semantic_cache=object(), guardrails=_FakeGuardrails()),
    )

    with pytest.raises(RuntimeError, match="reason_code=policy_input_block"):
        await worker._run_with_phase2_orchestrator(
            tenant_id="tenant-1",
            namespace="worker.execute",
            model_key="data_agent",
            query_text="blocked",
            executor=_ok_executor,
        )


