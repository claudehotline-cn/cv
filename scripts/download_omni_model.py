from huggingface_hub import snapshot_download
import time
import os

model_id = "cybermotaz/Qwen3-Omni-30B-A3B-Instruct-NVFP4"
local_dir = "/home/chaisen/projects/cv/models/qwen3-omni-30b-a3b-instruct-nvfp4"

max_retries = 10
print(f"Starting download of {model_id} to {local_dir}")

for i in range(max_retries):
    try:
        print(f"Attempt {i+1}/{max_retries}...")
        token = os.environ.get("HF_TOKEN")
        if token:
            print("Using HF_TOKEN for authentication.")
        else:
            print("No HF_TOKEN found. Using unauthenticated request.")
            
        snapshot_download(repo_id=model_id, local_dir=local_dir, resume_download=True, token=token)
        print("Download complete successfully!")
        break
    except Exception as e:
        print(f"Download failed with error: {e}")
        if i < max_retries - 1:
            print("Retrying in 10 seconds...")
            time.sleep(10)
        else:
            print("Max retries reached. Download failed.")
            sys.exit(1)
