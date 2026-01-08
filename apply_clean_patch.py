with open("original_model.py", "r") as f:
    lines = f.readlines()

new_lines = []
runner_tasks_block = [
    "_RUNNER_TASKS = {\n",
    '    "generate": ["generate", "text-generation", "Translation", "Summarization", "Question Answering", "Text-Generation", "Conversational", "text2text-generation"],\n',
    '    "pooling": ["embed", "embedding", "Feature Extraction", "Sentence Similarity", "fill-mask"],\n',
    "}\n\n"
]
task_option_line = "TaskOption = str\n"

imports_cleaned = False

for line in lines:
    # remove bad imports
    if "TaskOption," in line:
        line = line.replace("TaskOption,", "")
    if "_RUNNER_TASKS," in line:
        line = line.replace("_RUNNER_TASKS,", "")
    
    # insert before decorators
    if "@config" in line:
        new_lines.extend(runner_tasks_block)
        new_lines.append(task_option_line)
    
    new_lines.append(line)

with open("patched_model.py", "w") as f:
    f.writelines(new_lines)
