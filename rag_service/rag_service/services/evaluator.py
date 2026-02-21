"""RAG evaluation (LLM-as-a-Judge) via vLLM."""

from __future__ import annotations

import json
import logging
import re
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from ..config import settings
from .llm_service import llm_service


logger = logging.getLogger(__name__)


class MetricType(str, Enum):
    FAITHFULNESS = "faithfulness"
    ANSWER_RELEVANCE = "answer_relevance"
    CONTEXT_RELEVANCE = "context_relevance"


class EvaluationResult(BaseModel):
    score: float = Field(description="Evaluation score from 0.0 to 1.0")
    reasoning: str = Field(description="Reasoning for the score")


def _extract_json_object(text: str) -> Optional[dict]:
    s = (text or "").strip()
    if not s:
        return None

    if "</think>" in s:
        s = s.split("</think>")[-1].strip()

    m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, re.DOTALL)
    if m:
        s = m.group(1).strip()

    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                cand = s[start : i + 1]
                try:
                    return json.loads(cand)
                except Exception:
                    return None
    return None


class RAGEvaluator:
    async def evaluate_faithfulness(self, question: str, answer: str, contexts: List[str]) -> EvaluationResult:
        context_text = "\n\n".join(contexts)
        system = """你是一个专业的 RAG 系统评估专家。你的任务是评估系统生成的回答（Answer）是否完全基于提供的上下文（Context）推导得出。

请按 JSON 输出：
{"score": 0.0-1.0, "reasoning": "..."}
"""
        prompt = f"""[Context]
{context_text}

[Question]
{question}

[Answer]
{answer}
"""

        try:
            raw = await llm_service.generate(
                prompt,
                model=settings.llm_model,
                timeout_sec=settings.llm_timeout_sec,
                temperature=0.1,
                system_prompt=system,
            )
            obj = None
            try:
                obj = json.loads(raw)
            except Exception:
                obj = _extract_json_object(raw)

            if not isinstance(obj, dict):
                raise ValueError("Invalid JSON")
            return EvaluationResult(**obj)
        except Exception as e:
            logger.error("Faithfulness evaluation failed: %s", e)
            return EvaluationResult(score=0.0, reasoning=f"Evaluation Error: {e}")

    async def evaluate_answer_relevance(self, question: str, answer: str) -> EvaluationResult:
        system = """你是一个专业的 RAG 系统评估专家。你的任务是评估系统生成的回答（Answer）是否有效回答了用户的问题（Question）。

请按 JSON 输出：
{"score": 0.0-1.0, "reasoning": "..."}
"""
        prompt = f"""[Question]
{question}

[Answer]
{answer}
"""

        try:
            raw = await llm_service.generate(
                prompt,
                model=settings.llm_model,
                timeout_sec=settings.llm_timeout_sec,
                temperature=0.1,
                system_prompt=system,
            )
            obj = None
            try:
                obj = json.loads(raw)
            except Exception:
                obj = _extract_json_object(raw)
            if not isinstance(obj, dict):
                raise ValueError("Invalid JSON")
            return EvaluationResult(**obj)
        except Exception as e:
            logger.error("Answer relevance evaluation failed: %s", e)
            return EvaluationResult(score=0.0, reasoning=f"Evaluation Error: {e}")


rag_evaluator = RAGEvaluator()
