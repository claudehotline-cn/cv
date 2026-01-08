target_file = "/usr/local/lib/python3.12/dist-packages/vllm_omni/entrypoints/openai/api_server.py"
with open(target_file, "r") as f:
    lines = f.readlines()

new_lines = []
dummy_def = "def maybe_register_tokenizer_info_endpoint(args):\n    pass\n"
inserted_dummy = False

for line in lines:
    # Remove from import
    if "maybe_register_tokenizer_info_endpoint," in line:
        continue
    
    # Insert dummy definition before usage or near top
    # We can insert it after imports are done. 
    # Let's insert it before 'async def' or 'def' of the main function if we haven't yet.
    # Or just insert it after the last import.
    
    new_lines.append(line)

# Ideally we insert the dummy definition at a safe place. 
# Let's append it to the end of imports.
# Finding the end of imports is tricky simply reading lines.
# But we can just add it before the  definition or similar.

# Let's rewrite the file content string-wise for safety with the dummy def
content = "".join(new_lines)
if "maybe_register_tokenizer_info_endpoint" in content and "def maybe_register_tokenizer_info_endpoint" not in content:
   # usage exists but def doesn't. 
   # Insert def after imports.
   import_marker = "from vllm.entrypoints.openai.protocol import ChatCompletionRequest"
   if import_marker in content:
       content = content.replace(import_marker, import_marker + "\n\n" + dummy_def)
   else:
       # Fallback: insert at top after logger
       content = content.replace("logger = init_logger(__name__)", "logger = init_logger(__name__)\n\n" + dummy_def)

with open(target_file, "w") as f:
    f.write(content)
