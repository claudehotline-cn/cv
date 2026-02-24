from datetime import datetime, timezone
from collections import Counter
import inspect
import json
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.messages.utils import convert_to_openai_messages

from ..core.agent_registry import registry
from ..core.auth import AuthPrincipal, get_current_user, require_admin
from ..db import get_db
from ..models.db_models import (
    AgentModel,
    AgentVersionModel,
    EvalCaseModel,
    EvalDatasetModel,
    EvalResultModel,
    EvalRunModel,
    PromptTemplateModel,
    PromptVersionModel,
    TenantMembershipModel,
)

router = APIRouter(prefix="/agents/{agent_id}/eval", tags=["eval"])


def _tenant_uuid(user: AuthPrincipal) -> UUID:
    if not user.tenant_id:
        raise HTTPException(status_code=401, detail="Tenant context required")
    try:
        return UUID(str(user.tenant_id))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid tenant context") from exc


async def _ensure_tenant_membership_or_403(db: AsyncSession, user: AuthPrincipal, tenant_id: UUID) -> None:
    stmt = select(TenantMembershipModel).where(
        TenantMembershipModel.tenant_id == tenant_id,
        TenantMembershipModel.user_id == user.user_id,
        TenantMembershipModel.status == "active",
    )
    membership = (await db.execute(stmt)).scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=403, detail="Tenant membership required")


async def _get_agent_or_404(agent_id: str, db: AsyncSession) -> AgentModel:
    result = await db.execute(select(AgentModel).where(AgentModel.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def _get_dataset_or_404(dataset_id: str, db: AsyncSession) -> EvalDatasetModel:
    result = await db.execute(select(EvalDatasetModel).where(EvalDatasetModel.id == dataset_id))
    ds = result.scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Eval dataset not found")
    return ds


async def _get_run_or_404(run_id: str, db: AsyncSession) -> EvalRunModel:
    result = await db.execute(select(EvalRunModel).where(EvalRunModel.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Eval run not found")
    return run


class CreateDatasetRequest(BaseModel):
    name: str
    description: Optional[str] = None


class ImportCasesRequest(BaseModel):
    cases: list[Dict[str, Any]]


class CreateRunRequest(BaseModel):
    dataset_id: str
    config: Optional[Dict[str, Any]] = None


def _dataset_dict(ds: EvalDatasetModel) -> dict:
    return {
        "id": str(ds.id),
        "tenant_id": str(ds.tenant_id),
        "agent_id": str(ds.agent_id),
        "name": ds.name,
        "description": ds.description,
        "created_by": ds.created_by,
        "created_at": ds.created_at.isoformat() if ds.created_at else None,
        "updated_at": ds.updated_at.isoformat() if ds.updated_at else None,
    }


def _run_dict(run: EvalRunModel) -> dict:
    return {
        "id": str(run.id),
        "tenant_id": str(run.tenant_id),
        "dataset_id": str(run.dataset_id),
        "agent_id": str(run.agent_id),
        "agent_version": run.agent_version,
        "prompt_version_snapshot": run.prompt_version_snapshot,
        "status": run.status,
        "config": run.config,
        "summary": run.summary,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        return "".join(parts)
    return str(value)


def _normalize_tool_call(call: Any) -> Optional[dict]:
    if not isinstance(call, dict):
        return None

    fn_raw = call.get("function")
    fn: dict[str, Any] = fn_raw if isinstance(fn_raw, dict) else {}
    name = call.get("name") or fn.get("name") or call.get("tool") or call.get("tool_name")
    if not name:
        return None

    raw_args = call.get("arguments")
    if raw_args is None:
        raw_args = call.get("args")
    if raw_args is None and fn:
        raw_args = fn.get("arguments")

    if isinstance(raw_args, str):
        stripped = raw_args.strip()
        if stripped:
            try:
                parsed_args: Any = json.loads(stripped)
            except Exception:
                parsed_args = stripped
        else:
            parsed_args = {}
    elif raw_args is None:
        parsed_args = {}
    else:
        parsed_args = raw_args

    out = {
        "name": str(name),
        "arguments": parsed_args,
    }
    call_id = call.get("id")
    if call_id is not None:
        out["id"] = str(call_id)
    return out


def _ensure_openai_messages_list(messages: Any) -> list[dict]:
    if messages is None:
        return []

    payload = messages
    if isinstance(payload, dict) and "messages" in payload and isinstance(payload["messages"], list):
        payload = payload["messages"]

    try:
        converted = convert_to_openai_messages(payload)
    except Exception:
        converted = payload

    if isinstance(converted, dict):
        converted = [converted]
    if not isinstance(converted, list):
        converted = [converted]

    normalized: list[dict] = []
    for msg in converted:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").strip().lower()
        if not role:
            continue

        item: dict[str, Any] = {
            "role": role,
            "content": _normalize_text(msg.get("content")),
        }

        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list):
            normalized_calls: list[dict] = []
            for tc in tool_calls:
                normalized_tc = _normalize_tool_call(tc)
                if normalized_tc:
                    normalized_calls.append(normalized_tc)
            if normalized_calls:
                item["tool_calls"] = normalized_calls

        tool_call_id = msg.get("tool_call_id")
        if tool_call_id is not None:
            item["tool_call_id"] = str(tool_call_id)

        normalized.append(item)
    return normalized


def _extract_messages_from_output(output: Any) -> list[dict]:
    if isinstance(output, dict) and "messages" in output:
        return _ensure_openai_messages_list(output.get("messages"))
    return _ensure_openai_messages_list(output)


def _extract_tool_calls(messages: list[dict]) -> list[dict]:
    calls: list[dict] = []
    for msg in messages:
        tool_calls = msg.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for tc in tool_calls:
            normalized = _normalize_tool_call(tc)
            if normalized:
                calls.append({
                    "name": normalized["name"],
                    "arguments": normalized.get("arguments", {}),
                })
    return calls


def _extract_expected_tool_calls(expected_output: Any) -> list[dict]:
    if not isinstance(expected_output, dict):
        return []

    direct = expected_output.get("tool_calls")
    if isinstance(direct, list):
        normalized: list[dict] = []
        for item in direct:
            tc = _normalize_tool_call(item)
            if tc:
                normalized.append({"name": tc["name"], "arguments": tc.get("arguments", {})})
        if normalized:
            return normalized

    normalized = []

    trajectory = expected_output.get("trajectory")
    if isinstance(trajectory, list):
        for step in trajectory:
            if not isinstance(step, dict):
                continue
            if isinstance(step.get("tool_calls"), list):
                for item in step["tool_calls"]:
                    tc = _normalize_tool_call(item)
                    if tc:
                        normalized.append({"name": tc["name"], "arguments": tc.get("arguments", {})})
            else:
                tc = _normalize_tool_call(step)
                if tc:
                    normalized.append({"name": tc["name"], "arguments": tc.get("arguments", {})})

    return normalized


def _canonical_tool_call(call: dict) -> str:
    payload = {
        "name": str(call.get("name") or ""),
        "arguments": call.get("arguments", {}),
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


def _tool_calls_match(actual_calls: list[dict], expected_calls: list[dict], mode: str) -> bool:
    actual_tokens = [_canonical_tool_call(c) for c in actual_calls]
    expected_tokens = [_canonical_tool_call(c) for c in expected_calls]

    if mode == "unordered":
        return Counter(actual_tokens) == Counter(expected_tokens)
    if mode == "subset":
        actual_counter = Counter(actual_tokens)
        expected_counter = Counter(expected_tokens)
        return all(actual_counter[key] <= expected_counter[key] for key in actual_counter)
    if mode == "superset":
        actual_counter = Counter(actual_tokens)
        expected_counter = Counter(expected_tokens)
        return all(actual_counter[key] >= expected_counter[key] for key in expected_counter)
    return actual_tokens == expected_tokens


def _compute_trajectory_match_score(messages: list[dict], expected_output: Any, mode: str) -> tuple[Optional[float], dict]:
    expected_calls = _extract_expected_tool_calls(expected_output)
    actual_calls = _extract_tool_calls(messages)

    meta = {
        "trajectory_mode": mode,
        "expected_tool_calls": len(expected_calls),
        "actual_tool_calls": len(actual_calls),
    }

    if not expected_calls:
        return None, meta

    matched = _tool_calls_match(actual_calls, expected_calls, mode)
    return (1.0 if matched else 0.0), meta


def _extract_final_answer(messages: list[dict], output: Any) -> Optional[str]:
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = _normalize_text(msg.get("content")).strip()
            if content:
                return content

    if isinstance(output, dict):
        for key in ("final_answer", "answer", "output", "result"):
            if key in output and output.get(key) is not None:
                return str(output.get(key))

    if isinstance(output, str):
        stripped = output.strip()
        return stripped or None
    return None


def _build_eval_input_payload(raw_input: Any) -> dict:
    if isinstance(raw_input, dict):
        if isinstance(raw_input.get("messages"), list):
            return {"messages": raw_input["messages"]}
        if isinstance(raw_input.get("message"), str):
            return {"messages": [{"role": "user", "content": raw_input["message"]}]}
        raise ValueError("Case input must include messages or message")

    if isinstance(raw_input, str):
        return {"messages": [{"role": "user", "content": raw_input}]}

    raise ValueError("Unsupported case input format")


def _reference_messages_from_expected(expected_output: Any) -> list[dict]:
    if not isinstance(expected_output, dict):
        return []

    trajectory = expected_output.get("trajectory")
    if isinstance(trajectory, list) and trajectory:
        return _ensure_openai_messages_list(trajectory)

    tool_calls = _extract_expected_tool_calls(expected_output)
    if tool_calls:
        openai_tool_calls = []
        for idx, tc in enumerate(tool_calls):
            openai_tool_calls.append(
                {
                    "type": "function",
                    "id": f"expected_call_{idx}",
                    "function": {
                        "name": tc.get("name") or "",
                        "arguments": json.dumps(tc.get("arguments", {}), ensure_ascii=False, default=str),
                    },
                }
            )
        return [{"role": "assistant", "content": "", "tool_calls": openai_tool_calls}]

    final_answer = expected_output.get("final_answer")
    if final_answer is not None:
        return [{"role": "assistant", "content": str(final_answer)}]
    return []


def _to_llm_judge_messages(messages: list[dict]) -> list[dict]:
    converted: list[dict] = []
    for idx, msg in enumerate(messages):
        role = str(msg.get("role") or "").strip().lower()
        if not role:
            continue

        item: dict[str, Any] = {
            "role": role,
            "content": _normalize_text(msg.get("content")),
        }

        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list):
            openai_tool_calls: list[dict[str, Any]] = []
            for tc_idx, tc in enumerate(tool_calls):
                normalized = _normalize_tool_call(tc)
                if not normalized:
                    continue
                args = normalized.get("arguments", {})
                if isinstance(args, str):
                    args_str = args
                else:
                    args_str = json.dumps(args, ensure_ascii=False, default=str)

                openai_tool_calls.append(
                    {
                        "type": "function",
                        "id": normalized.get("id") or f"call_{idx}_{tc_idx}",
                        "function": {
                            "name": normalized.get("name") or "",
                            "arguments": args_str,
                        },
                    }
                )

            if openai_tool_calls:
                item["tool_calls"] = openai_tool_calls

        tool_call_id = msg.get("tool_call_id")
        if tool_call_id:
            item["tool_call_id"] = str(tool_call_id)

        converted.append(item)
    return converted


def _to_numeric_score(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


async def _compute_llm_judge_score(actual_messages: list[dict], expected_output: Any, model: str) -> tuple[Optional[float], Optional[str]]:
    reference_messages = _reference_messages_from_expected(expected_output)
    if not reference_messages:
        return None, None

    judge_actual = _to_llm_judge_messages(actual_messages)
    judge_reference = _to_llm_judge_messages(reference_messages)
    if not judge_actual or not judge_reference:
        return None, "llm_judge messages not available"

    try:
        from agentevals.trajectory.llm import create_trajectory_llm_as_judge, TRAJECTORY_ACCURACY_PROMPT
    except Exception as exc:
        return None, f"llm_judge import failed: {exc}"

    try:
        evaluator = create_trajectory_llm_as_judge(model=model, prompt=TRAJECTORY_ACCURACY_PROMPT)
        result = evaluator(outputs=judge_actual, reference_outputs=judge_reference)
        if inspect.isawaitable(result):
            result = await result

        if isinstance(result, dict):
            score = _to_numeric_score(result.get("score"))
            if score is not None:
                return score, None
        return None, "llm_judge did not return a numeric score"
    except Exception as exc:
        return None, str(exc)


async def _snapshot_prompt_versions(db: AsyncSession, tenant_id: UUID, agent_key: Optional[str]) -> Optional[dict]:
    if not agent_key:
        return None

    stmt = (
        select(PromptTemplateModel, PromptVersionModel)
        .outerjoin(PromptVersionModel, PromptTemplateModel.published_version_id == PromptVersionModel.id)
        .where(PromptTemplateModel.key.like(f"{agent_key}.%"))
        .where(or_(PromptTemplateModel.tenant_id == tenant_id, PromptTemplateModel.tenant_id.is_(None)))
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return None

    tenant_id_str = str(tenant_id)
    snapshot: dict[str, dict[str, Any]] = {}
    for tmpl, ver in rows:
        current = {
            "template_id": str(tmpl.id),
            "tenant_id": str(tmpl.tenant_id) if tmpl.tenant_id else None,
            "version_id": str(ver.id) if ver else None,
            "version": ver.version if ver else None,
            "status": ver.status if ver else None,
            "key": tmpl.key,
        }

        existing = snapshot.get(tmpl.key)
        if not existing:
            snapshot[tmpl.key] = current
            continue

        existing_is_tenant = existing.get("tenant_id") == tenant_id_str
        current_is_tenant = current.get("tenant_id") == tenant_id_str
        if current_is_tenant and not existing_is_tenant:
            snapshot[tmpl.key] = current
            continue
        if existing_is_tenant and not current_is_tenant:
            continue

        existing_version = existing.get("version") or 0
        current_version = current.get("version") or 0
        if current_version > existing_version:
            snapshot[tmpl.key] = current

    return snapshot


@router.get("/datasets")
async def list_eval_datasets(
    agent_id: str,
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_uuid(user)
    await _ensure_tenant_membership_or_403(db, user, tenant_id)
    await _get_agent_or_404(agent_id, db)

    stmt = select(EvalDatasetModel).where(
        EvalDatasetModel.tenant_id == tenant_id,
        EvalDatasetModel.agent_id == agent_id,
    ).order_by(EvalDatasetModel.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [_dataset_dict(r) for r in rows]}


@router.post("/datasets")
async def create_eval_dataset(
    agent_id: str,
    body: CreateDatasetRequest,
    user: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_uuid(user)
    await _ensure_tenant_membership_or_403(db, user, tenant_id)
    await _get_agent_or_404(agent_id, db)

    ds = EvalDatasetModel(
        tenant_id=tenant_id,
        agent_id=UUID(agent_id),
        name=body.name,
        description=body.description,
        created_by=user.user_id,
    )
    db.add(ds)
    await db.commit()
    await db.refresh(ds)
    return _dataset_dict(ds)


@router.post("/datasets/{dataset_id}/import")
async def import_eval_cases(
    agent_id: str,
    dataset_id: str,
    body: ImportCasesRequest,
    user: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_uuid(user)
    await _ensure_tenant_membership_or_403(db, user, tenant_id)
    await _get_agent_or_404(agent_id, db)
    ds = await _get_dataset_or_404(dataset_id, db)

    if str(ds.tenant_id) != str(tenant_id) or str(ds.agent_id) != agent_id:
        raise HTTPException(status_code=404, detail="Eval dataset not found")

    inserted = 0
    for case in body.cases:
        if not isinstance(case, dict) or "input" not in case:
            raise HTTPException(status_code=400, detail="Each case must include input")
        c = EvalCaseModel(
            dataset_id=ds.id,
            input=case.get("input"),
            expected_output=case.get("expected_output"),
            tags=case.get("tags") or [],
            notes=case.get("notes"),
        )
        db.add(c)
        inserted += 1

    await db.commit()
    return {"dataset_id": str(ds.id), "inserted": inserted}


@router.get("/datasets/{dataset_id}/cases")
async def list_eval_cases(
    agent_id: str,
    dataset_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_uuid(user)
    await _ensure_tenant_membership_or_403(db, user, tenant_id)
    await _get_agent_or_404(agent_id, db)
    ds = await _get_dataset_or_404(dataset_id, db)

    if str(ds.tenant_id) != str(tenant_id) or str(ds.agent_id) != agent_id:
        raise HTTPException(status_code=404, detail="Eval dataset not found")

    total_stmt = select(func.count()).select_from(
        select(EvalCaseModel.id).where(EvalCaseModel.dataset_id == ds.id).subquery()
    )
    total = (await db.execute(total_stmt)).scalar() or 0

    stmt = (
        select(EvalCaseModel)
        .where(EvalCaseModel.dataset_id == ds.id)
        .order_by(EvalCaseModel.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()

    items = [
        {
            "id": str(r.id),
            "dataset_id": str(r.dataset_id),
            "input": r.input,
            "expected_output": r.expected_output,
            "tags": r.tags,
            "notes": r.notes,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/runs")
async def create_eval_run(
    agent_id: str,
    body: CreateRunRequest,
    user: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_uuid(user)
    await _ensure_tenant_membership_or_403(db, user, tenant_id)
    agent = await _get_agent_or_404(agent_id, db)
    ds = await _get_dataset_or_404(body.dataset_id, db)

    if str(ds.tenant_id) != str(tenant_id) or str(ds.agent_id) != agent_id:
        raise HTTPException(status_code=404, detail="Eval dataset not found")

    agent_key = agent.builtin_key
    plugin = registry.get_plugin(agent_key) if agent_key else None
    if not plugin:
        raise HTTPException(status_code=400, detail="Eval execution currently supports built-in agents only")

    graph = plugin.get_graph()

    run_config = body.config or {}
    requested_evaluators_raw = run_config.get("evaluators")
    if isinstance(requested_evaluators_raw, list):
        requested_evaluators = {str(item) for item in requested_evaluators_raw if item}
    else:
        requested_evaluators = {"trajectory_match"}

    trajectory_mode = str(run_config.get("trajectory_match_mode", "strict")).strip().lower()
    if trajectory_mode not in {"strict", "unordered", "subset", "superset"}:
        trajectory_mode = "strict"

    llm_judge_model = str(run_config.get("llm_judge_model", "openai:gpt-4o"))
    trajectory_threshold = _coerce_float(run_config.get("trajectory_pass_threshold", 1.0), 1.0)
    llm_judge_threshold = _coerce_float(run_config.get("llm_judge_pass_threshold", 0.7), 0.7)

    agent_version = 0
    if agent.published_version_id:
        pv = await db.get(AgentVersionModel, agent.published_version_id)
        if pv:
            agent_version = pv.version

    prompt_snapshot = await _snapshot_prompt_versions(db, tenant_id, agent_key)

    run = EvalRunModel(
        tenant_id=tenant_id,
        dataset_id=ds.id,
        agent_id=UUID(agent_id),
        agent_version=agent_version,
        prompt_version_snapshot=prompt_snapshot,
        status="pending",
        config=run_config,
        summary={"total": 0, "passed": 0, "failed": 0, "errors": 0, "avg_score": 0.0},
    )
    db.add(run)
    await db.flush()

    run.status = "running"
    run.started_at = datetime.now(timezone.utc)

    cases_stmt = select(EvalCaseModel).where(EvalCaseModel.dataset_id == ds.id)
    cases = (await db.execute(cases_stmt)).scalars().all()

    passed = 0
    failed = 0
    errors = 0
    case_scores: list[float] = []

    for case in cases:
        case_started_at = datetime.now(timezone.utc)
        case_completed_at = case_started_at
        case_status = "error"
        actual_output: Optional[dict] = None
        trajectory_payload: Optional[dict] = None
        scores: dict[str, Any] = {}
        error_message: Optional[str] = None

        try:
            input_payload = _build_eval_input_payload(case.input)
            invoke_config: dict[str, Any] = {
                "configurable": {
                    "thread_id": f"eval-{run.id}-{case.id}",
                    "session_id": f"eval-{run.id}",
                    "user_id": user.user_id,
                },
                "metadata": {
                    "eval_run_id": str(run.id),
                    "eval_case_id": str(case.id),
                    "agent_id": agent_id,
                    "agent_key": agent_key,
                },
                "tags": ["eval", str(agent_key or "agent")],
            }
            if agent_key == "data_agent":
                invoke_config["configurable"]["analysis_id"] = f"eval-{run.id}-{case.id}"

            output = await graph.ainvoke(input_payload, config=invoke_config)
            messages = _extract_messages_from_output(output)
            actual_tool_calls = _extract_tool_calls(messages)
            final_answer = _extract_final_answer(messages, output)

            actual_output = {
                "final_answer": final_answer,
                "messages": messages,
            }
            trajectory_payload = {
                "tool_calls": actual_tool_calls,
                "message_count": len(messages),
            }

            score_parts: list[float] = []

            if "trajectory_match" in requested_evaluators:
                trajectory_score, trajectory_meta = _compute_trajectory_match_score(
                    messages,
                    case.expected_output,
                    trajectory_mode,
                )
                scores.update(trajectory_meta)
                if trajectory_score is not None:
                    scores["trajectory_match"] = trajectory_score
                    score_parts.append(trajectory_score)

            if "llm_judge" in requested_evaluators:
                llm_score, llm_error = await _compute_llm_judge_score(
                    actual_messages=messages,
                    expected_output=case.expected_output,
                    model=llm_judge_model,
                )
                if llm_score is not None:
                    scores["llm_judge"] = llm_score
                    score_parts.append(llm_score)
                if llm_error:
                    scores["llm_judge_error"] = llm_error

            pass_flags: list[bool] = []
            if isinstance(scores.get("trajectory_match"), (int, float)):
                pass_flags.append(float(scores["trajectory_match"]) >= trajectory_threshold)
            if isinstance(scores.get("llm_judge"), (int, float)):
                pass_flags.append(float(scores["llm_judge"]) >= llm_judge_threshold)

            if pass_flags:
                case_status = "passed" if all(pass_flags) else "failed"
            else:
                case_status = "passed"

            if score_parts:
                case_scores.append(sum(score_parts) / len(score_parts))
            elif case_status == "passed":
                case_scores.append(1.0)

        except Exception as exc:
            case_status = "error"
            error_message = str(exc)[:2000]
            scores["exception"] = type(exc).__name__
        finally:
            case_completed_at = datetime.now(timezone.utc)

        if case_status == "passed":
            passed += 1
        elif case_status == "failed":
            failed += 1
        else:
            errors += 1

        result = EvalResultModel(
            run_id=run.id,
            case_id=case.id,
            status=case_status,
            actual_output=actual_output,
            trajectory=trajectory_payload,
            scores=scores,
            error_message=error_message,
            started_at=case_started_at,
            completed_at=case_completed_at,
        )
        db.add(result)

    total = len(cases)
    avg_score = (sum(case_scores) / len(case_scores)) if case_scores else 0.0
    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc)
    run.summary = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "avg_score": avg_score,
    }

    await db.commit()
    await db.refresh(run)
    return _run_dict(run)


@router.get("/runs")
async def list_eval_runs(
    agent_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_uuid(user)
    await _ensure_tenant_membership_or_403(db, user, tenant_id)
    await _get_agent_or_404(agent_id, db)

    stmt = (
        select(EvalRunModel)
        .where(
            EvalRunModel.tenant_id == tenant_id,
            EvalRunModel.agent_id == agent_id,
        )
        .order_by(EvalRunModel.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    runs = (await db.execute(stmt)).scalars().all()
    return {"items": [_run_dict(r) for r in runs], "limit": limit, "offset": offset}


@router.get("/runs/{run_id}")
async def get_eval_run(
    agent_id: str,
    run_id: str,
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_uuid(user)
    await _ensure_tenant_membership_or_403(db, user, tenant_id)
    run = await _get_run_or_404(run_id, db)

    if str(run.tenant_id) != str(tenant_id) or str(run.agent_id) != agent_id:
        raise HTTPException(status_code=404, detail="Eval run not found")

    return _run_dict(run)


@router.get("/runs/{run_id}/results")
async def list_eval_results(
    agent_id: str,
    run_id: str,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_uuid(user)
    await _ensure_tenant_membership_or_403(db, user, tenant_id)
    run = await _get_run_or_404(run_id, db)

    if str(run.tenant_id) != str(tenant_id) or str(run.agent_id) != agent_id:
        raise HTTPException(status_code=404, detail="Eval run not found")

    stmt = (
        select(EvalResultModel)
        .where(EvalResultModel.run_id == run.id)
        .order_by(EvalResultModel.started_at.asc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()

    items = [
        {
            "id": str(r.id),
            "run_id": str(r.run_id),
            "case_id": str(r.case_id),
            "status": r.status,
            "actual_output": r.actual_output,
            "trajectory": r.trajectory,
            "scores": r.scores,
            "error_message": r.error_message,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in rows
    ]
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/runs/{run_id_1}/compare/{run_id_2}")
async def compare_eval_runs(
    agent_id: str,
    run_id_1: str,
    run_id_2: str,
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_uuid(user)
    await _ensure_tenant_membership_or_403(db, user, tenant_id)

    r1 = await _get_run_or_404(run_id_1, db)
    r2 = await _get_run_or_404(run_id_2, db)

    if (
        str(r1.tenant_id) != str(tenant_id)
        or str(r2.tenant_id) != str(tenant_id)
        or str(r1.agent_id) != agent_id
        or str(r2.agent_id) != agent_id
    ):
        raise HTTPException(status_code=404, detail="Eval run not found")

    s1 = r1.summary or {}
    s2 = r2.summary or {}

    return {
        "run_1": {"id": str(r1.id), "summary": s1},
        "run_2": {"id": str(r2.id), "summary": s2},
        "delta": {
            "total": (s2.get("total", 0) - s1.get("total", 0)),
            "passed": (s2.get("passed", 0) - s1.get("passed", 0)),
            "avg_score": (float(s2.get("avg_score", 0.0)) - float(s1.get("avg_score", 0.0))),
        },
    }
