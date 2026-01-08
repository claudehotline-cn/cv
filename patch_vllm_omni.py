import os

target_file = "/usr/local/lib/python3.12/dist-packages/vllm_omni/config/model.py"

with open(target_file, "r") as f:
    content = f.read()

# Remove the import of _RUNNER_TASKS
content = content.replace("    _RUNNER_TASKS,\n", "")

# Add definition of _RUNNER_TASKS if missing
if "_RUNNER_TASKS =" not in content:
    # Use standard default values inferred from vLLM codebase
    runner_tasks_def = """
_RUNNER_TASKS = {
    "generate": ["generate", "text-generation", "Translation", "Summarization", "Question Answering", "Text-Generation", "Conversational", "text2text-generation"],
    "pooling": ["embed", "embedding", "Feature Extraction", "Sentence Similarity", "fill-mask"],
}
"""
    # Insert after imports
    import_end_idx = content.find("class OmniModelConfig")
    if import_end_idx != -1:
        content = content[:import_end_idx] + runner_tasks_def + "\n" + content[import_end_idx:]

with open(target_file, "w") as f:
    f.write(content)
