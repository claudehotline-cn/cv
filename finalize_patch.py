import os

target_file = "/usr/local/lib/python3.12/dist-packages/vllm_omni/config/model.py"

with open(target_file, "r") as f:
    content = f.read()

# Remove TaskOption from import
content = content.replace("    TaskOption,\n", "")

# Define TaskOption locally
# Insert it along with _RUNNER_TASKS (which should be there) or after imports
if "TaskOption =" not in content:
    task_option_def = "TaskOption = str\n"
    # Find start of file or after imports
    import_end_idx = content.find("class OmniModelConfig")
    if import_end_idx != -1:
         # insert before
         content = content[:import_end_idx] + task_option_def + content[import_end_idx:]

with open(target_file, "w") as f:
    f.write(content)
