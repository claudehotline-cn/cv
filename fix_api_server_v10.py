target_file = "/usr/local/lib/python3.12/dist-packages/vllm_omni/entrypoints/openai/api_server.py"
with open(target_file, "r") as f:
    content = f.read()

# The bad block to search for
bad_block = """from vllm.entrypoints.openai.protocol import ChatCompletionRequest

def maybe_register_tokenizer_info_endpoint(args):
    pass
, ChatCompletionResponse, ErrorResponse"""

# The good replacement
good_block = """from vllm.entrypoints.openai.protocol import ChatCompletionRequest, ChatCompletionResponse, ErrorResponse

def maybe_register_tokenizer_info_endpoint(args):
    pass"""

if bad_block in content:
    content = content.replace(bad_block, good_block)
else:
    # If indentation varies, try a more aggressive normalization or just manual reconstruction
    # Let's try to remove the orphaned line and fix the import
    content = content.replace(", ChatCompletionResponse, ErrorResponse", "")
    content = content.replace("import ChatCompletionRequest", "import ChatCompletionRequest, ChatCompletionResponse, ErrorResponse")

with open(target_file, "w") as f:
    f.write(content)
