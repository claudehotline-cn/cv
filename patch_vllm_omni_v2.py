import os

target_file = "/usr/local/lib/python3.12/dist-packages/vllm_omni/config/model.py"

with open(target_file, "r") as f:
    content = f.read()

# First, remove the bad insertion if present (unlikely since we started fresh container, or did we? 
# Wait, vllm-omni:fixed has the bad code now. We need to fix THAT.)
# Remove the bad block between decorators and class
# The pattern was: @dataclass(...)\n\n_RUNNER_TASKS = {...}\n\nclass OmniModelConfig
# We will just strip it out and re-insert correctly.

# Remove existing _RUNNER_TASKS definition if found (to clean up the mess)
import re
content = re.sub(r"_RUNNER_TASKS = \{.*?\}\n", "", content, flags=re.DOTALL)

# Re-insert correctly after logger definition
runner_tasks_def = """
_RUNNER_TASKS = {
    "generate": ["generate", "text-generation", "Translation", "Summarization", "Question Answering", "Text-Generation", "Conversational", "text2text-generation"],
    "pooling": ["embed", "embedding", "Feature Extraction", "Sentence Similarity", "fill-mask"],
}
"""

insert_marker = "logger = init_logger(__name__)"
if insert_marker in content:
    content = content.replace(insert_marker, insert_marker + "\n" + runner_tasks_def)

with open(target_file, "w") as f:
    f.write(content)
