target_file = "original_api_server.py"
with open(target_file, "r") as f:
    lines = f.readlines()

new_lines = []
dummy_def = "def maybe_register_tokenizer_info_endpoint(args):\n    pass\n"

for line in lines:
    # 1. Remove from import: '    maybe_register_tokenizer_info_endpoint,'
    if "maybe_register_tokenizer_info_endpoint," in line:
        continue
    
    # 2. Mock usage: '        maybe_register_tokenizer_info_endpoint(args)'
    # Actually we can keep the usage if we define the function.
    
    # 3. Insert definition
    # Insert at module level, e.g. after 'logger = ...'
    if "logger = init_logger(__name__)" in line:
        new_lines.append(line)
        new_lines.append("\n" + dummy_def + "\n")
        continue

    new_lines.append(line)

with open("patched_api_server.py", "w") as f:
    f.writelines(new_lines)
