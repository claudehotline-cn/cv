target_file = "/usr/local/lib/python3.12/dist-packages/vllm_omni/entrypoints/async_omni_llm.py"
with open(target_file, "r") as f:
    content = f.read()

# Replace the import
# Old: from vllm.tokenizers import init_tokenizer_from_config
# New: from vllm.tokenizers import cached_tokenizer_from_config as init_tokenizer_from_config
if "from vllm.tokenizers import init_tokenizer_from_config" in content:
    content = content.replace(
        "from vllm.tokenizers import init_tokenizer_from_config",
        "from vllm.tokenizers import cached_tokenizer_from_config as init_tokenizer_from_config"
    )

with open(target_file, "w") as f:
    f.write(content)
