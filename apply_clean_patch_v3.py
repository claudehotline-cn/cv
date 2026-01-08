with open("original_model_clean.py", "r") as f:
    lines = f.readlines()

new_lines = []
runner_tasks_block = [
    "_RUNNER_TASKS = {\n",
    '    "generate": ["generate", "text-generation", "Translation", "Summarization", "Question Answering", "Text-Generation", "Conversational", "text2text-generation"],\n',
    '    "pooling": ["embed", "embedding", "Feature Extraction", "Sentence Similarity", "fill-mask"],\n',
    "}\n\n"
]
task_option_line = "TaskOption = str\n"
is_gguf_fixed_import = "from vllm.transformers_utils.gguf_utils import is_gguf\n"

for line in lines:
    # remove bad imports or moved imports
    if "TaskOption," in line:
        line = line.replace("TaskOption,", "")
    if "_RUNNER_TASKS," in line:
        line = line.replace("_RUNNER_TASKS,", "")
    
    # Fix is_gguf import: It was inside a multi-line import from utils
    # Original: from vllm.transformers_utils.utils import ( is_gguf, ... )
    # We will just remove it from there and add a new import line
    if "is_gguf," in line:
        line = line.replace("is_gguf,", "") # remove from utils block
    
    # Insert definitions before decorators
    if "@config" in line:
        new_lines.extend(runner_tasks_block)
        new_lines.append(task_option_line)
        new_lines.append(is_gguf_fixed_import)
    
    new_lines.append(line)

with open("patched_model_clean_v3.py", "w") as f:
    f.writelines(new_lines)
