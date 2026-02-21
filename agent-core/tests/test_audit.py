import asyncio
import uuid
from unittest.mock import AsyncMock

from langchain_core.outputs import Generation, LLMResult

from agent_core.audit import AuditCallbackHandler


class MockEmitter:
    def __init__(self):
        self.emit = AsyncMock()


def test_audit_callback_tool_lifecycle_emits_requested_and_executed():
    async def run():
        emitter = MockEmitter()
        handler = AuditCallbackHandler(emitter=emitter)

        request_id = str(uuid.uuid4())
        tool_run_id = uuid.uuid4()

        await handler.on_tool_start(
            serialized={"name": "test_tool"},
            input_str="test input",
            run_id=tool_run_id,
            metadata={
                "request_id": request_id,
                "session_id": "test_session",
                "thread_id": "test_thread",
            },
        )
        await handler.on_tool_end(
            output="test output",
            run_id=tool_run_id,
        )

        event_types = [c.kwargs.get("event_type") for c in emitter.emit.call_args_list]
        assert event_types == ["tool_call_requested", "tool_call_executed"]

        for call in emitter.emit.call_args_list:
            assert call.kwargs.get("request_id") == request_id

    asyncio.run(run())


def test_audit_callback_chain_llm_and_run_events():
    async def run():
        emitter = MockEmitter()
        handler = AuditCallbackHandler(emitter=emitter)

        request_id = str(uuid.uuid4())
        chain_run_id = uuid.uuid4()
        llm_run_id = uuid.uuid4()

        await handler.on_chain_start(
            serialized={"name": "test_chain"},
            inputs={"input": "hello"},
            run_id=chain_run_id,
            tags=["agent:test_agent"],
            metadata={
                "request_id": request_id,
                "session_id": "test_session",
                "thread_id": "test_thread",
            },
        )
        await handler.on_llm_start(
            serialized={},
            prompts=["User: hello"],
            invocation_params={"model_name": "gpt-4"},
            run_id=llm_run_id,
            parent_run_id=chain_run_id,
            metadata={
                "request_id": request_id,
                "session_id": "test_session",
                "thread_id": "test_thread",
            },
        )
        await handler.on_llm_end(
            response=LLMResult(generations=[[Generation(text="Hi there")]]),
            run_id=llm_run_id,
        )
        await handler.on_chain_end(
            outputs={"output": "Hi there"},
            run_id=chain_run_id,
        )

        event_types = [c.kwargs.get("event_type") for c in emitter.emit.call_args_list]
        assert event_types == [
            "run_started",
            "subagent_started",
            "llm_called",
            "llm_output_received",
            "subagent_finished",
            "run_finished",
        ]

    asyncio.run(run())
