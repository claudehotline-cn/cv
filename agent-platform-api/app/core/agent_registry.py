from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone
from app.db import AsyncSessionLocal
from app.models.db_models import AgentModel, AgentVersionModel, PromptTemplateModel, PromptVersionModel
from .plugin_loader import load_plugins
from .prompt_resolver import collect_all_builtin_prompts, BUILTIN_PROMPTS
import logging

_LOGGER = logging.getLogger(__name__)

class AgentRegistry:
    def __init__(self):
        self.plugins = load_plugins()

    async def sync_plugins(self, session: AsyncSession):
        """Ensure all loaded plugins exist in DB as builtin agents."""
        for key, agent in self.plugins.items():
            config = agent.get_config()
            stmt = select(AgentModel).where(AgentModel.builtin_key == key)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if not existing:
                _LOGGER.info(f"Registering new builtin agent: {key}")
                new_agent = AgentModel(
                    name=config.get("name", key),
                    type="builtin",
                    builtin_key=key,
                    config=config
                )
                session.add(new_agent)
                await session.flush()

                ver = AgentVersionModel(
                    agent_id=new_agent.id,
                    version=1,
                    status="published",
                    config=config,
                    change_summary="Initial builtin registration",
                )
                session.add(ver)
                await session.flush()
                new_agent.published_version_id = ver.id
            else:
                _LOGGER.debug(f"Builtin agent {key} already exists")
                if existing.config != config:
                    existing.config = config

                    # Determine next version number
                    max_ver = await session.execute(
                        select(func.coalesce(func.max(AgentVersionModel.version), 0))
                        .where(AgentVersionModel.agent_id == existing.id)
                    )
                    next_ver = max_ver.scalar() + 1

                    # Archive current published version
                    if existing.published_version_id:
                        old_pub = await session.get(AgentVersionModel, existing.published_version_id)
                        if old_pub:
                            old_pub.status = "archived"

                    ver = AgentVersionModel(
                        agent_id=existing.id,
                        version=next_ver,
                        status="published",
                        config=config,
                        change_summary="Auto-updated from plugin config change",
                    )
                    session.add(ver)
                    await session.flush()
                    existing.published_version_id = ver.id
                    session.add(existing)

                # Backfill: if agent exists but has no published_version_id yet
                if not existing.published_version_id:
                    max_ver = await session.execute(
                        select(func.coalesce(func.max(AgentVersionModel.version), 0))
                        .where(AgentVersionModel.agent_id == existing.id)
                    )
                    next_ver = max_ver.scalar() + 1
                    ver = AgentVersionModel(
                        agent_id=existing.id,
                        version=next_ver,
                        status="published",
                        config=existing.config,
                        change_summary="Backfill from existing config",
                    )
                    session.add(ver)
                    await session.flush()
                    existing.published_version_id = ver.id
                    session.add(existing)

        await session.commit()

        # Sync builtin prompts after agents
        await self._sync_builtin_prompts(session)

    async def _sync_builtin_prompts(self, session: AsyncSession):
        """Register/update builtin prompt constants into prompt_templates + prompt_versions."""
        plugin_keys = list(self.plugins.keys())
        collect_all_builtin_prompts(plugin_keys)
        _LOGGER.info(f"Collected {len(BUILTIN_PROMPTS)} builtin prompts from {len(plugin_keys)} plugins")

        for key, content in BUILTIN_PROMPTS.items():
            stmt = select(PromptTemplateModel).where(
                PromptTemplateModel.tenant_id.is_(None),
                PromptTemplateModel.key == key,
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if not existing:
                _LOGGER.info(f"Registering builtin prompt: {key}")
                parts = key.split(".")
                category = parts[0] if parts else "general"
                tmpl = PromptTemplateModel(
                    tenant_id=None,
                    key=key,
                    name=key,
                    description=f"Builtin prompt from {category}",
                    category=category,
                )
                session.add(tmpl)
                await session.flush()

                ver = PromptVersionModel(
                    template_id=tmpl.id,
                    version=1,
                    status="published",
                    content=content,
                    change_summary="Initial builtin registration",
                )
                session.add(ver)
                await session.flush()
                tmpl.published_version_id = ver.id
                ver.published_at = datetime.now(timezone.utc)
            else:
                # Check if content changed
                current_content = None
                if existing.published_version_id:
                    pub_ver = await session.get(PromptVersionModel, existing.published_version_id)
                    if pub_ver:
                        current_content = pub_ver.content

                if current_content != content:
                    _LOGGER.info(f"Updating builtin prompt: {key}")
                    max_ver = await session.execute(
                        select(func.coalesce(func.max(PromptVersionModel.version), 0))
                        .where(PromptVersionModel.template_id == existing.id)
                    )
                    next_ver = max_ver.scalar() + 1

                    if existing.published_version_id:
                        old_pub = await session.get(PromptVersionModel, existing.published_version_id)
                        if old_pub and old_pub.status == "published":
                            old_pub.status = "archived"

                    ver = PromptVersionModel(
                        template_id=existing.id,
                        version=next_ver,
                        status="published",
                        content=content,
                        change_summary="Auto-updated from plugin prompt change",
                    )
                    session.add(ver)
                    await session.flush()
                    existing.published_version_id = ver.id
                    ver.published_at = datetime.now(timezone.utc)

        await session.commit()

    def get_plugin(self, key: str):
        return self.plugins.get(key)

# Global Registry Instance
registry = AgentRegistry()
