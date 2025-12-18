"""RAG 效果评估服务 (LLM-as-a-Judge)"""

import logging
import json
from enum import Enum
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from pydantic import BaseModel, Field

from ..config import settings

logger = logging.getLogger(__name__)


class MetricType(str, Enum):
    FAITHFULNESS = "faithfulness"
    ANSWER_RELEVANCE = "answer_relevance"
    CONTEXT_RELEVANCE = "context_relevance"


class EvaluationResult(BaseModel):
    score: float = Field(description="Evaluation score from 0.0 to 1.0")
    reasoning: str = Field(description="Reasoning for the score")


class RAGEvaluator:
    """RAG 评估器"""
    
    def __init__(self):
        # 使用配置的 LLM，通过 JsonOutputParser 强制输出 JSON
        # 注意: 评估通常需要较强的指令遵循能力
        self.llm = ChatOllama(
            model=settings.llm_model,
            base_url=settings.ollama_base_url,
            temperature=0.1, # 评估需要确定性
            format="json",   # 强制 JSON 模式
        )
        self.parser = JsonOutputParser(pydantic_object=EvaluationResult)

    async def evaluate_faithfulness(self, question: str, answer: str, contexts: List[str]) -> EvaluationResult:
        """
        评估信实度 (Faithfulness): 回答是否忠实于上下文?
        
        Args:
            question: 用户问题
            answer: RAG生成的回答
            contexts: 检索到的上下文片段列表
        """
        context_text = "\n\n".join(contexts)
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一个专业的 RAG 系统评估专家。你的任务是评估系统生成的回答（Answer）是否完全基于提供的上下文（Context）推导得出。
            
你需要检查：
1. 回答中的每一条陈述，是否都能在上下文中找到依据？
2. 回答是否包含上下文中不存在的幻觉信息？

请按以下 JSON 格式输出评估结果：
{{
    "score": <0.0 到 1.0 之间的分数，1.0 表示完全忠实，0.0 表示完全幻觉>,
    "reasoning": "<简短的打分理由>"
}}
"""),
            ("user", """
[Context]
{context}

[Question]
{question}

[Answer]
{answer}
""")
        ])
        
        chain = prompt | self.llm | self.parser
        
        try:
            result = await chain.ainvoke({
                "context": context_text,
                "question": question,
                "answer": answer
            })
            return EvaluationResult(**result)
        except Exception as e:
            logger.error(f"Faithfulness evaluation failed: {e}")
            return EvaluationResult(score=0.0, reasoning=f"Evaluation Error: {str(e)}")

    async def evaluate_answer_relevance(self, question: str, answer: str) -> EvaluationResult:
        """
        评估回答相关性 (Answer Relevance): 回答是否解决了用户的问题?
        """
        prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一个专业的 RAG 系统评估专家。你的任务是评估系统生成的回答（Answer）是否有效回答了用户的问题（Question）。
            
你需要检查：
1. 回答是否直接切题？
2. 回答是否完整？
3. 回答是否因答非所问而显得无用？

请按以下 JSON 格式输出评估结果：
{{
    "score": <0.0 到 1.0 之间的分数，1.0 表示完美回答，0.0 表示完全不相关>,
    "reasoning": "<简短的打分理由>"
}}
"""),
            ("user", """
[Question]
{question}

[Answer]
{answer}
""")
        ])
        
        chain = prompt | self.llm | self.parser
        
        try:
            result = await chain.ainvoke({
                "question": question,
                "answer": answer
            })
            return EvaluationResult(**result)
        except Exception as e:
            logger.error(f"Answer Relevance evaluation failed: {e}")
            return EvaluationResult(score=0.0, reasoning=f"Evaluation Error: {str(e)}")


# 单例
rag_evaluator = RAGEvaluator()
