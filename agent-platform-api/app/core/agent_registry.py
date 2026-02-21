from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import AsyncSessionLocal
from app.models.db_models import AgentModel
from .plugin_loader import load_plugins
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
            else:
                _LOGGER.debug(f"Builtin agent {key} already exists")
                # Optional: Update config if changed
                if existing.config != config:
                     existing.config = config
                     session.add(existing)

        await session.commit()
    
    def get_plugin(self, key: str):
        return self.plugins.get(key)

# Global Registry Instance
registry = AgentRegistry()
