import pytest
from langchain_core.outputs import LLMResult
from agent_core.observability import TokenCostCallback

def test_token_cost_calculation():
    """Test cost calculation logic for gpt-4o."""
    callback = TokenCostCallback(model_name="gpt-4o")
    
    # Mock LLM Output
    response = LLMResult(
        generations=[],
        llm_output={
            "token_usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 1000,
                "total_tokens": 2000
            }
        }
    )
    
    callback.on_llm_end(response)
    
    # Expected:
    # Input: 1k * 0.0025 = 2.50
    # Output: 1k * 0.01 = 10.00
    # Total: 12.50 ? Wait, pricing in code is per 1k?
    # Code: (prompt / 1000) * rates["input"]
    # 1000/1000 * 0.0025 = 0.0025
    # 1000/1000 * 0.01 = 0.01
    # Total = 0.0125
    
    assert callback.total_tokens == 2000
    assert abs(callback.total_cost - 0.0125) < 0.0001

def test_token_cost_accumulation():
    """Test accumulation over multiple calls."""
    callback = TokenCostCallback(model_name="gpt-4o")
    
    response = LLMResult(
        generations=[],
        llm_output={
            "token_usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 0,
                "total_tokens": 1000
            }
        }
    )
    
    # Call twice
    callback.on_llm_end(response)
    callback.on_llm_end(response)
    
    # Cost per call: 0.0025
    # Total: 0.0050
    assert abs(callback.total_cost - 0.0050) < 0.0001
