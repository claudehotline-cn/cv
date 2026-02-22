from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Column, String, Boolean, DateTime, Text,  ForeignKey, Integer, Float, UniqueConstraint, Index, func, LargeBinary
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

from ..db import Base

class AgentModel(Base):
    __tablename__ = "agents"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'builtin' | 'custom'
    builtin_key: Mapped[Optional[str]] = mapped_column(String(50), nullable=True) # e.g. 'data_agent'
    config: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default={})

    published_version_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agent_versions.id", use_alter=True), nullable=True
    )
    draft_version_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agent_versions.id", use_alter=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    sessions: Mapped[List["SessionModel"]] = relationship("SessionModel", back_populates="agent")
    versions: Mapped[List["AgentVersionModel"]] = relationship(
        "AgentVersionModel", back_populates="agent", foreign_keys="AgentVersionModel.agent_id"
    )


class AgentVersionModel(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version", name="uq_agent_versions_agent_version"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    agent_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")  # draft / published / archived
    config: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default={})
    change_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(100), ForeignKey("platform_users.user_id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    agent: Mapped["AgentModel"] = relationship(
        "AgentModel", back_populates="versions", foreign_keys=[agent_id]
    )


class PlatformUserModel(Base):
    """Platform-local user shadow table for FK constraints on business data."""

    __tablename__ = "platform_users"

    user_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TenantModel(Base):
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TenantMembershipModel(Base):
    __tablename__ = "tenant_memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_tenant_memberships_tenant_user"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(100), ForeignKey("platform_users.user_id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), default="member", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SessionModel(Base):
    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(100), ForeignKey("platform_users.user_id"), nullable=True, index=True)
    agent_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id"),
        nullable=True,
    )
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    thread_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), default=uuid4, nullable=True) # Checkpointer Thread ID
    state: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True) # Checkpoint State
    
    is_interrupted: Mapped[bool] = mapped_column(Boolean, default=False)
    interrupt_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    agent: Mapped["AgentModel"] = relationship("AgentModel", back_populates="sessions")
    messages: Mapped[List["MessageModel"]] = relationship("MessageModel", back_populates="session", cascade="all, delete-orphan")


class MessageModel(Base):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False) # user, assistant, system
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    thinking: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tool_calls: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSONB, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    session: Mapped["SessionModel"] = relationship("SessionModel", back_populates="messages")


class TaskModel(Base):
    """异步任务模型"""
    __tablename__ = "tasks"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(100), ForeignKey("platform_users.user_id"), nullable=True, index=True)
    
    # 任务状态: pending, running, completed, failed, cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    progress: Mapped[int] = mapped_column(default=0)  # 0-100
    progress_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # 结果
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # 取消支持
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    session: Mapped["SessionModel"] = relationship("SessionModel")



class AgentRunModel(Base):
    """一次 DeepAgent 执行实例（一次用户消息触发 / 一次 job）"""
    __tablename__ = "agent_runs"

    request_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    # request_id field (String) removed as it is now redundant with PK
    conversation_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    thread_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    root_agent_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    entrypoint: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    initiator_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True) # user / system / scheduler
    initiator_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    env: Mapped[Optional[str]] = mapped_column(String(20), default="prod")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running") # running, succeeded, failed
    error_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[Optional[List[str]]] = mapped_column(JSONB, nullable=True)

class AgentSpanModel(Base):
    """一次子步骤或节点执行"""
    __tablename__ = "agent_spans"

    span_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    request_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agent_runs.request_id"), nullable=False)
    parent_span_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agent_spans.span_id"), nullable=True)
    span_type: Mapped[str] = mapped_column(String(50), nullable=False) # tool, chain, llm, node
    agent_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    subagent_kind: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    graph_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    node_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    node_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    attempt: Mapped[int] = mapped_column(default=1)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")
    input_blob_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    output_blob_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    meta: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

class AuditEventModel(Base):
    """核心审计事件流"""
    __tablename__ = "audit_events"

    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    request_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agent_runs.request_id"), nullable=False)
    span_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agent_spans.span_id"), nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    thread_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    actor_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    component: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    target_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    severity: Mapped[str] = mapped_column(String(20), default="info")
    decision: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default={})
    payload_blob_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    prev_hash: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    hash: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

class ToolAuditModel(Base):
    """工具调用的结构化审计"""
    __tablename__ = "tool_audits"

    tool_event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    request_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agent_runs.request_id"), nullable=False)
    span_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agent_spans.span_id"), nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    thread_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(200), nullable=False)
    tool_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    request_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    response_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    side_effect_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    resource: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    input_blob_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    output_blob_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    input_digest: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_digest: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    approval_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

class AuditBlobModel(Base):
    """大对象存储"""
    __tablename__ = "audit_blobs"

    blob_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    content_type: Mapped[str] = mapped_column(String(100), default="text/plain")
    compression: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=True)

class ApprovalRequestModel(Base):
    """HITL 审批请求"""
    __tablename__ = "approval_requests"

    approval_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    request_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agent_runs.request_id"), nullable=False)
    span_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agent_spans.span_id"), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    policy_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    action_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    risk_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    proposed_action_blob_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

class ApprovalDecisionModel(Base):
    """HITL 审批决策"""
    __tablename__ = "approval_decisions"

    decision_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    approval_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("approval_requests.approval_id"), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decider_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    decision: Mapped[str] = mapped_column(String(20), nullable=False) # approved, rejected
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    edited_action_blob_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)


class AuthAuditEventModel(Base):
    """认证安全审计事件（独立于 Agent Run/Span 审计树）。"""

    __tablename__ = "auth_audit_events"

    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    component: Mapped[str] = mapped_column(String(50), default="auth", nullable=False)

    user_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    actor_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    actor_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    ip_addr: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    result: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    reason_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default={})


class TenantRateLimitPolicyModel(Base):
    __tablename__ = "tenant_rate_limit_policies"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, unique=True, index=True)
    read_limit: Mapped[str] = mapped_column(String(20), nullable=False, default="300/min")
    write_limit: Mapped[str] = mapped_column(String(20), nullable=False, default="120/min")
    execute_limit: Mapped[str] = mapped_column(String(20), nullable=False, default="60/min")
    user_read_limit: Mapped[str] = mapped_column(String(20), nullable=False, default="120/min")
    user_write_limit: Mapped[str] = mapped_column(String(20), nullable=False, default="60/min")
    user_execute_limit: Mapped[str] = mapped_column(String(20), nullable=False, default="20/min")
    tenant_concurrency_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    user_concurrency_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    fail_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TenantQuotaPolicyModel(Base):
    __tablename__ = "tenant_quota_policies"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, unique=True, index=True)
    monthly_token_quota: Mapped[int] = mapped_column(nullable=False, default=50000000)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TenantQuotaUsageModel(Base):
    __tablename__ = "tenant_quota_usages"
    __table_args__ = (UniqueConstraint("tenant_id", "period", name="uq_tenant_quota_usages_tenant_period"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    prompt_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    request_count: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SecretModel(Base):
    __tablename__ = "secrets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "scope", "owner_user_id", "name", name="uq_secrets_tenant_scope_owner_name"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    owner_user_id: Mapped[Optional[str]] = mapped_column(String(100), ForeignKey("platform_users.user_id"), nullable=True, index=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SecretVersionModel(Base):
    __tablename__ = "secret_versions"
    __table_args__ = (UniqueConstraint("secret_id", "version", name="uq_secret_versions_secret_version"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    secret_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("secrets.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    crypto_alg: Mapped[str] = mapped_column(String(50), nullable=False, default="aes_gcm_v1")
    key_ref: Mapped[str] = mapped_column(String(100), nullable=False)
    nonce: Mapped[str] = mapped_column(Text, nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    enc_meta: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PromptTemplateModel(Base):
    __tablename__ = "prompt_templates"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_prompt_templates_tenant_key"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    published_version_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("prompt_versions.id", use_alter=True), nullable=True
    )
    draft_version_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("prompt_versions.id", use_alter=True), nullable=True
    )

    created_by: Mapped[Optional[str]] = mapped_column(String(100), ForeignKey("platform_users.user_id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    versions: Mapped[List["PromptVersionModel"]] = relationship(
        "PromptVersionModel", back_populates="template", foreign_keys="PromptVersionModel.template_id"
    )


class PromptVersionModel(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("template_id", "version", name="uq_prompt_versions_template_version"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    template_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("prompt_templates.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")  # draft / published / archived
    content: Mapped[str] = mapped_column(Text, nullable=False)
    variables_schema: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    change_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(100), ForeignKey("platform_users.user_id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    template: Mapped["PromptTemplateModel"] = relationship(
        "PromptTemplateModel", back_populates="versions", foreign_keys=[template_id]
    )


class PromptABTestModel(Base):
    __tablename__ = "prompt_ab_tests"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    template_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("prompt_templates.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")  # running / completed / cancelled
    variant_a_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("prompt_versions.id"), nullable=False)
    variant_b_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("prompt_versions.id"), nullable=False)
    traffic_split: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    metrics: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default={})
    winner_version_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("prompt_versions.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class EvalDatasetModel(Base):
    __tablename__ = "eval_datasets"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    agent_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(100), ForeignKey("platform_users.user_id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EvalCaseModel(Base):
    __tablename__ = "eval_cases"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("eval_datasets.id"), nullable=False, index=True)
    input: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    expected_output: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    tags: Mapped[List[Any]] = mapped_column(JSONB, nullable=False, default=[])
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvalRunModel(Base):
    __tablename__ = "eval_runs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    dataset_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("eval_datasets.id"), nullable=False, index=True)
    agent_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False, index=True)
    agent_version: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_version_snapshot: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending / running / completed / failed
    config: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default={})
    summary: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvalResultModel(Base):
    __tablename__ = "eval_results"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("eval_runs.id"), nullable=False, index=True)
    case_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("eval_cases.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending / running / passed / failed / error
    actual_output: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    trajectory: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    scores: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default={})
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


Index("idx_auth_audit_event_time", AuthAuditEventModel.event_time.desc())
Index("idx_auth_audit_event_type_time", AuthAuditEventModel.event_type, AuthAuditEventModel.event_time.desc())
Index("idx_auth_audit_user_time", AuthAuditEventModel.user_id, AuthAuditEventModel.event_time.desc())
Index("idx_auth_audit_ip_time", AuthAuditEventModel.ip_addr, AuthAuditEventModel.event_time.desc())
