"""Generic filesystem backend for agent workspace management.

Provides both sync and async APIs for file operations, with automatic
directory structure management for different agent types.
"""
from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
from typing import Any, Dict, List, Optional

try:
    import aiofiles
    HAS_AIOFILES = True
except ImportError:
    HAS_AIOFILES = False

from .settings import get_settings

_LOGGER = logging.getLogger("agent_core.filesystem")


class WorkspaceBackend:
    """Generic filesystem backend for all agents.
    
    Directory structure:
    - Sync:  /data/workspace/{user_id}/{agent_name}/{session_id}/artifacts/
    - Async: /data/workspace/{user_id}/{agent_name}/{session_id}/tasks/{task_id}/
    - Tmp:   /data/workspace/{user_id}/{agent_name}/{session_id}/[tasks/{task_id}/]tmp/
    
    Usage:
        # Sync operations
        backend = WorkspaceBackend("data_agent", "user_123", session_id)
        backend.write_json("plans/outline.json", data)
        
        # Async operations
        await backend.awrite_json("plans/outline.json", data)
    """
    
    def __init__(
        self,
        agent_name: str,
        user_id: str,
        session_id: str,
        task_id: Optional[str] = None,
    ):
        self.agent_name = agent_name
        self.user_id = user_id
        self.session_id = session_id
        self.task_id = task_id
        self._settings = get_settings()
    
    # ========== Path Properties ==========
    
    @property
    def base_dir(self) -> str:
        """Get session base directory: /{workspace_root}/{user_id}/{agent_name}/{session_id}/"""
        return os.path.join(
            self._settings.workspace_root,
            self.user_id,
            self.agent_name,
            self.session_id,
        )
    
    @property
    def tmp_dir(self) -> str:
        """Get temporary files directory.
        
        Sync:  /{base_dir}/tmp/
        Async: /{base_dir}/tasks/{task_id}/tmp/
        """
        if self.task_id:
            return os.path.join(self.base_dir, "tasks", self.task_id, "tmp")
        return os.path.join(self.base_dir, "tmp")
    
    @property
    def artifacts_dir(self) -> str:
        """Get artifacts directory.
        
        Sync:  /{base_dir}/artifacts/
        Async: /{base_dir}/tasks/{task_id}/
        """
        if self.task_id:
            return os.path.join(self.base_dir, "tasks", self.task_id)
        return os.path.join(self.base_dir, "artifacts")
    
    def get_path(self, relative_path: str) -> str:
        """Get full path from relative path within artifacts_dir."""
        return os.path.join(self.artifacts_dir, relative_path)
    
    # ========== Sync Methods ==========
    
    def exists(self, path: str) -> bool:
        """Check if file exists."""
        return os.path.exists(self.get_path(path))
    
    def ensure_dir(self, subdir: str = "") -> str:
        """Ensure directory exists, return full path."""
        full_path = self.get_path(subdir) if subdir else self.artifacts_dir
        os.makedirs(full_path, exist_ok=True)
        return full_path
    
    def read_json(self, path: str) -> Dict[str, Any]:
        """Read JSON file, return empty dict if not exists."""
        full_path = self.get_path(path)
        if not os.path.exists(full_path):
            return {}
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            _LOGGER.warning(f"Failed to read JSON {path}: {e}")
            return {}
    
    def write_json(self, path: str, data: Dict[str, Any]) -> str:
        """Write JSON file, return full path."""
        full_path = self.get_path(path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        try:
            with open(full_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            _LOGGER.debug(f"Wrote JSON to {full_path}")
            return full_path
        except Exception as e:
            _LOGGER.warning(f"Failed to write JSON {path}: {e}")
            return ""
    
    def read_text(self, path: str) -> str:
        """Read text file, return empty string if not exists."""
        full_path = self.get_path(path)
        if not os.path.exists(full_path):
            return ""
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            _LOGGER.warning(f"Failed to read text {path}: {e}")
            return ""
    
    def write_text(self, path: str, content: str) -> str:
        """Write text file, return full path."""
        full_path = self.get_path(path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        try:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            _LOGGER.debug(f"Wrote text to {full_path}")
            return full_path
        except Exception as e:
            _LOGGER.warning(f"Failed to write text {path}: {e}")
            return ""
    
    def list_files(self, subdir: str = "", pattern: str = "*") -> List[str]:
        """List files matching pattern in subdir."""
        search_dir = self.get_path(subdir) if subdir else self.artifacts_dir
        if not os.path.exists(search_dir):
            return []
        return glob.glob(os.path.join(search_dir, pattern))
    
    def delete(self, path: str) -> bool:
        """Delete file, return True if successful."""
        full_path = self.get_path(path)
        try:
            if os.path.exists(full_path):
                os.remove(full_path)
                return True
            return False
        except Exception as e:
            _LOGGER.warning(f"Failed to delete {path}: {e}")
            return False
    
    # ========== Async Methods ==========
    
    async def aexists(self, path: str) -> bool:
        """Check if file exists (async)."""
        return await asyncio.to_thread(self.exists, path)
    
    async def aensure_dir(self, subdir: str = "") -> str:
        """Ensure directory exists (async), return full path."""
        return await asyncio.to_thread(self.ensure_dir, subdir)
    
    async def aread_json(self, path: str) -> Dict[str, Any]:
        """Read JSON file (async), return empty dict if not exists."""
        full_path = self.get_path(path)
        if not os.path.exists(full_path):
            return {}
        
        if HAS_AIOFILES:
            try:
                async with aiofiles.open(full_path, "r", encoding="utf-8") as f:
                    content = await f.read()
                return json.loads(content)
            except Exception as e:
                _LOGGER.warning(f"Failed to read JSON {path}: {e}")
                return {}
        else:
            return await asyncio.to_thread(self.read_json, path)
    
    async def awrite_json(self, path: str, data: Dict[str, Any]) -> str:
        """Write JSON file (async), return full path."""
        full_path = self.get_path(path)
        await asyncio.to_thread(os.makedirs, os.path.dirname(full_path), exist_ok=True)
        
        if HAS_AIOFILES:
            try:
                async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
                    await f.write(json.dumps(data, ensure_ascii=False, indent=2))
                _LOGGER.debug(f"Wrote JSON to {full_path}")
                return full_path
            except Exception as e:
                _LOGGER.warning(f"Failed to write JSON {path}: {e}")
                return ""
        else:
            return await asyncio.to_thread(self.write_json, path, data)
    
    async def aread_text(self, path: str) -> str:
        """Read text file (async), return empty string if not exists."""
        full_path = self.get_path(path)
        if not os.path.exists(full_path):
            return ""
        
        if HAS_AIOFILES:
            try:
                async with aiofiles.open(full_path, "r", encoding="utf-8") as f:
                    return await f.read()
            except Exception as e:
                _LOGGER.warning(f"Failed to read text {path}: {e}")
                return ""
        else:
            return await asyncio.to_thread(self.read_text, path)
    
    async def awrite_text(self, path: str, content: str) -> str:
        """Write text file (async), return full path."""
        full_path = self.get_path(path)
        await asyncio.to_thread(os.makedirs, os.path.dirname(full_path), exist_ok=True)
        
        if HAS_AIOFILES:
            try:
                async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
                    await f.write(content)
                _LOGGER.debug(f"Wrote text to {full_path}")
                return full_path
            except Exception as e:
                _LOGGER.warning(f"Failed to write text {path}: {e}")
                return ""
        else:
            return await asyncio.to_thread(self.write_text, path, content)
    
    async def alist_files(self, subdir: str = "", pattern: str = "*") -> List[str]:
        """List files matching pattern in subdir (async)."""
        return await asyncio.to_thread(self.list_files, subdir, pattern)
    
    async def adelete(self, path: str) -> bool:
        """Delete file (async), return True if successful."""
        return await asyncio.to_thread(self.delete, path)


__all__ = ["WorkspaceBackend"]
