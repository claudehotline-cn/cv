"""
Prompt Resolver — resolve prompt templates from DB with Jinja2 rendering,
falling back to builtin hardcoded constants.
"""
from __future__ import annotations

import importlib
import hashlib
import logging
import re
from typing import Dict, Optional

import jinja2
from jinja2 import BaseLoader, Environment
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import PromptTemplateModel, PromptVersionModel, PromptABTestModel

_LOGGER = logging.getLogger(__name__)


class PromptResolver:
    """Prompt template registry + renderer."""

    BUILTIN_PROMPTS: Dict[str, str] = {}
    _jinja_env = Environment(loader=BaseLoader(), undefined=jinja2.Undefined)

    @classmethod
    def _collect_module_prompts(cls, module_path: str, key_prefix: str):
        """Import a module and collect uppercase string constants as prompts."""
        try:
            mod = importlib.import_module(module_path)
        except Exception as e:
            _LOGGER.warning(f"Cannot import {module_path}: {e}")
            return

        for attr_name in dir(mod):
            if attr_name.startswith("_") or not attr_name.isupper():
                continue
            val = getattr(mod, attr_name)
            if isinstance(val, str) and len(val) > 20:
                full_key = f"{key_prefix}.{attr_name}"
                cls.BUILTIN_PROMPTS[full_key] = val

    @classmethod
    def collect_all_builtin_prompts(cls, plugin_keys: list[str]):
        """Collect builtin prompts for all configured plugins."""
        for key in plugin_keys:
            cls._collect_module_prompts(f"{key}.prompts", key)
            cls._collect_module_prompts(f"{key}.tools.prompts", f"{key}.tools")

    @staticmethod
    def extract_variables(content: str) -> list[str]:
        """Extract Jinja2 variable names from a prompt template string."""
        return list(set(re.findall(r"\{\{\s*(\w+)\s*\}\}", content)))

    @classmethod
    def _render_text(cls, content: str, variables: Optional[Dict[str, str]]) -> str:
        if not variables:
            return content

        result = content

        # 1) Python format style: {var}
        for k, v in variables.items():
            result = result.replace(f"{{{k}}}", str(v))

        # 2) Jinja2 style: {{ var }}
        try:
            tmpl = cls._jinja_env.from_string(result)
            result = tmpl.render(**variables)
        except Exception as e:
            _LOGGER.warning(f"Jinja2 render failed, fallback to manual replacement: {e}")
            for k, v in variables.items():
                result = result.replace("{{ " + k + " }}", str(v))
                result = result.replace("{{" + k + "}}", str(v))

        return result

    @classmethod
    async def resolve(
        cls,
        db: AsyncSession,
        tenant_id: Optional[str],
        key: str,
        variables: Optional[Dict[str, str]] = None,
        ab_test_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """
        Resolve prompt by key:
        1) DB published version
        2) builtin fallback
        3) render variables
        """
        content: Optional[str] = None

        tmpl_stmt = select(PromptTemplateModel).where(PromptTemplateModel.key == key)
        if tenant_id:
            tmpl_stmt = tmpl_stmt.where(PromptTemplateModel.tenant_id == tenant_id)
        else:
            tmpl_stmt = tmpl_stmt.where(PromptTemplateModel.tenant_id.is_(None))

        tmpl_result = await db.execute(tmpl_stmt)
        tmpl = tmpl_result.scalar_one_or_none()

        if tmpl:
            selected_version_id = tmpl.published_version_id

            selected_ab: Optional[PromptABTestModel] = None
            if ab_test_id:
                ab_stmt = select(PromptABTestModel).where(
                    PromptABTestModel.id == ab_test_id,
                    PromptABTestModel.template_id == tmpl.id,
                    PromptABTestModel.status == "running",
                )
                ab_result = await db.execute(ab_stmt)
                selected_ab = ab_result.scalar_one_or_none()
            else:
                ab_stmt = (
                    select(PromptABTestModel)
                    .where(
                        PromptABTestModel.template_id == tmpl.id,
                        PromptABTestModel.status == "running",
                    )
                    .order_by(PromptABTestModel.created_at.desc())
                    .limit(1)
                )
                ab_result = await db.execute(ab_stmt)
                selected_ab = ab_result.scalar_one_or_none()

            if selected_ab:
                bucket_seed = user_id or "anonymous"
                digest = hashlib.md5(bucket_seed.encode("utf-8")).hexdigest()
                ratio = int(digest[:8], 16) / float(0xFFFFFFFF)
                if ratio < float(selected_ab.traffic_split):
                    selected_version_id = selected_ab.variant_a_id
                else:
                    selected_version_id = selected_ab.variant_b_id

            if selected_version_id:
                version_result = await db.execute(
                    select(PromptVersionModel.content).where(PromptVersionModel.id == selected_version_id)
                )
                row = version_result.scalar_one_or_none()
                if row:
                    content = row

        if content is None:
            content = cls.BUILTIN_PROMPTS.get(key)

        if content is None:
            raise KeyError(f"Prompt key not found: {key}")

        return cls._render_text(content, variables)

    @classmethod
    async def preview_render(cls, content: str, variables: Optional[Dict[str, str]] = None) -> str:
        """Render prompt content for preview endpoint."""
        return cls._render_text(content, variables)


# Backward-compatible module-level exports
BUILTIN_PROMPTS = PromptResolver.BUILTIN_PROMPTS


def collect_all_builtin_prompts(plugin_keys: list[str]):
    PromptResolver.collect_all_builtin_prompts(plugin_keys)


def extract_variables(content: str) -> list[str]:
    return PromptResolver.extract_variables(content)


async def resolve(
    db: AsyncSession,
    tenant_id: Optional[str],
    key: str,
    variables: Optional[Dict[str, str]] = None,
    ab_test_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> str:
    return await PromptResolver.resolve(db, tenant_id, key, variables, ab_test_id, user_id)


async def preview_render(content: str, variables: Optional[Dict[str, str]] = None) -> str:
    return await PromptResolver.preview_render(content, variables)
