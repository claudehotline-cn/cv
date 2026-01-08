import os

target_file = "/usr/local/lib/python3.12/dist-packages/vllm_omni/config/model.py"

with open(target_file, "r") as f:
    lines = f.readlines()

new_lines = []
found_config = False
runner_tasks_inserted = False
task_option_inserted = False

# Definitions we want to enforce
runner_tasks_block = [
    "_RUNNER_TASKS = {\n",
    '    "generate": ["generate", "text-generation", "Translation", "Summarization", "Question Answering", "Text-Generation", "Conversational", "text2text-generation"],\n',
    '    "pooling": ["embed", "embedding", "Feature Extraction", "Sentence Similarity", "fill-mask"],\n',
    "}\n\n"
]
task_option_line = "TaskOption = str\n"

for line in lines:
    # Skip existing bad lines to clean up
    if line.strip().startswith("_RUNNER_TASKS =") or line.strip().startswith('"generate":') or line.strip().startswith('"pooling":') or line.strip() == "}":
        continue
    if line.strip().startswith("TaskOption ="):
        continue
    
    # Insert before decorators
    if "@config" in line and not found_config:
        new_lines.extend(runner_tasks_block)
        new_lines.append(task_option_line)
        found_config = True
    
    new_lines.append(line)

with open(target_file, "w") as f:
    f.writelines(new_lines)
