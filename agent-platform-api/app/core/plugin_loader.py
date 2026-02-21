import importlib
import logging
from typing import Dict, Type
from agent_core.base import BaseAgent
from agent_core.settings import get_settings

_LOGGER = logging.getLogger(__name__)

def load_plugins() -> Dict[str, BaseAgent]:
    """Load all configured agent plugins."""
    settings = get_settings()
    loaded_agents: Dict[str, BaseAgent] = {}
    
    for module_path in settings.installed_agents:
        try:
            _LOGGER.info(f"Loading plugin: {module_path}")
            module = importlib.import_module(module_path)
            
            # Look for 'DataAgent' class or any subclass of BaseAgent
            agent_instance = None
            
            # convention: look for class named same as module tail TitleCase? 
            # Or look for any class inheriting BaseAgent?
            # Or convention: module has 'agent' variable or 'Agent' class?
            
            # Strategy 1: Look for subclass of BaseAgent
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, BaseAgent) and attr is not BaseAgent:
                    agent_instance = attr()
                    break
            
            if not agent_instance:
                 _LOGGER.warning(f"No BaseAgent subclass found in {module_path}")
                 continue

            config = agent_instance.get_config()
            key = config.get("key", module_path.split(".")[-1])
            loaded_agents[key] = agent_instance
            _LOGGER.info(f"Loaded agent plugin: {key}")
            
        except Exception as e:
            _LOGGER.error(f"Failed to load plugin {module_path}: {e}")
            
    return loaded_agents
