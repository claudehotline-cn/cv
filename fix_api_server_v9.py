with open("original_api_server_broken.py", "r") as f:
    content = f.read()

# Fix the specific syntax error string
# likely: 
#    base,
#    build_app,
#    load_log_config,
#    
#    , ChatCompletionResponse
content = content.replace("\n    , ChatCompletionResponse", "\n    ChatCompletionResponse")

# Also ensure mock function is present
if "def maybe_register_tokenizer_info_endpoint" not in content:
    content = content.replace("logger = init_logger(__name__)", "logger = init_logger(__name__)\n\ndef maybe_register_tokenizer_info_endpoint(args):\n    pass\n")

with open("patched_api_server_v9.py", "w") as f:
    f.write(content)
