
filepath = r"d:\Projects\ai\cv\article_agent\article_agent\deep_agent\tools.py"
with open(filepath, "r", encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        if "from .llm_runtime" in line or "import build_chat_llm" in line:
            print(f"{i}: {line.strip()}")
