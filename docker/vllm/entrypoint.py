import sys
import runpy

# Minimal entrypoint to run vLLM
if __name__ == "__main__":
    # Just print args for debugging visibility
    print(f"Starting vLLM (Clean run) with args: {sys.argv}")
    
    # Delegate execution directly to standard vLLM entrypoint
    sys.exit(runpy.run_module("vllm.entrypoints.openai.api_server", run_name="__main__", alter_sys=True))
