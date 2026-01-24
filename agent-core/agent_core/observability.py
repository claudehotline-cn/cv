import logging
import time
from typing import Any, Dict, List, Optional
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

_LOGGER = logging.getLogger(__name__)

class TokenCostCallback(BaseCallbackHandler):
    """
    Callback to track and log token usage and estimated cost.
    
    Supports OpenAI pricing model.
    """
    
    def __init__(self, model_name: str = "gpt-4o"):
        self.model_name = model_name
        self.total_tokens = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_cost = 0.0
        
        # Simplified Pricing Table (per 1k tokens)
        self.pricing = {
            "gpt-4o": {"input": 0.0025, "output": 0.01},
            "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
            # Add local models as 0 cost
            "qwen": {"input": 0, "output": 0} 
        }

    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any) -> Any:
        """Run when LLM starts running."""
        # _LOGGER.debug(f"[TokenCost] LLM Started")
        pass

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> Any:
        """Run when LLM ends running."""
        try:
            # Extract usage from LLMResult
            # OpenAI returns 'token_usage' in llm_output
            if response.llm_output and "token_usage" in response.llm_output:
                usage = response.llm_output["token_usage"]
                prompt = usage.get("prompt_tokens", 0)
                completion = usage.get("completion_tokens", 0)
                total = usage.get("total_tokens", 0)
                
                self.prompt_tokens += prompt
                self.completion_tokens += completion
                self.total_tokens += total
                
                # Calculate Cost
                cost = self._calculate_cost(prompt, completion)
                self.total_cost += cost
                
                _LOGGER.info(
                    f"[TokenCost] Run Cost: ${cost:.6f} | "
                    f"Tokens: {total} (P:{prompt}, C:{completion}) | "
                    f"Total Session: ${self.total_cost:.4f}"
                )
                
                # TODO: Emit Metric to OTel / Prometheus here
                
        except Exception as e:
            _LOGGER.warning(f"[TokenCost] Failed to calculate cost: {e}")

    def _calculate_cost(self, prompt: int, completion: int) -> float:
        # Match model prefix
        rates = {"input": 0, "output": 0}
        
        # Rough matching logic
        target_model = self.model_name.lower()
        if "gpt-4" in target_model:
            rates = self.pricing.get("gpt-4o", rates) # Default generic gpt-4 to 4o rates
        elif "gpt-3.5" in target_model:
            rates = self.pricing.get("gpt-3.5-turbo", rates)
            
        input_cost = (prompt / 1000) * rates["input"]
        output_cost = (completion / 1000) * rates["output"]
        return input_cost + output_cost
        
# Placeholder for OTel setup
def setup_opentelemetry(service_name: str, otlp_endpoint: str = "http://jaeger:4317"):
    """
    Configure OpenTelemetry Auto-Instrumentation.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        
        # Instrument LangChain
        from openinference.instrumentation.langchain import LangChainInstrumentor
        LangChainInstrumentor().instrument()
        
        _LOGGER.info(f"[Observability] OTel instrumented for {service_name} -> {otlp_endpoint}")
        return True
    except ImportError:
        _LOGGER.warning("[Observability] opentelemetry libs not found. Skipping instrumentation.")
        return False
    except Exception as e:
        _LOGGER.error(f"[Observability] Failed to setup OTel: {e}")
        return False
