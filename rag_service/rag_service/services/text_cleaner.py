"""Text cleaning utilities for ingestion.

Cleaning rules are stored on KnowledgeBase and applied before chunking/embedding.
"""

from __future__ import annotations

import html
import re
import unicodedata
from typing import Any, Dict


DEFAULT_RULES: Dict[str, bool] = {
    "removeWhitespace": True,
    "stripHtml": True,
    "fixEncoding": False,
    "consolidateShortParagraphs": True,
}


def normalize_rules(rules: Any) -> Dict[str, bool]:
    if not isinstance(rules, dict):
        return dict(DEFAULT_RULES)
    out = dict(DEFAULT_RULES)
    for k in out.keys():
        if k in rules:
            out[k] = bool(rules.get(k))
    return out


def apply_cleaning_rules(content: str, rules: Any) -> str:
    text = content or ""
    r = normalize_rules(rules)

    if r.get("fixEncoding"):
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("\u00a0", " ")  # NBSP
        # Remove common zero-width characters
        text = re.sub(r"[\u200B-\u200D\uFEFF]", "", text)
        text = unicodedata.normalize("NFKC", text)

    if r.get("stripHtml"):
        if "<" in text and ">" in text:
            # Basic tag stripping (best-effort). Keep it deterministic and dependency-free.
            text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
            text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)

    if r.get("removeWhitespace"):
        # Collapse excessive blank lines and spaces.
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        # Strip line boundaries.
        lines = [ln.strip() for ln in text.split("\n")]
        text = "\n".join(lines).strip()

    if r.get("consolidateShortParagraphs"):
        # Merge very short paragraphs into the previous one.
        parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        merged = []
        min_len = 80
        for p in parts:
            if merged and len(p) < min_len:
                merged[-1] = (merged[-1].rstrip() + " " + p.lstrip()).strip()
            else:
                merged.append(p)
        text = "\n\n".join(merged).strip()

    return text
