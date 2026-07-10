"""
download_model.py -- fetches the default local LLM (GGUF format) into
models/, using huggingface_hub (a pip package -- no external installer,
no git-lfs, nothing outside your venv).

Usage:
    cd ai-voice-sales-agent
    python3 scripts/download_model.py
    python3 scripts/download_model.py --model larger   # bigger/better, needs more RAM
"""

import argparse
import os

from huggingface_hub import hf_hub_download

MODELS = {
    "default": {
        # ~2.2GB, runs fine on CPU with 8GB+ RAM. Good default for a laptop.
        "repo_id": "Qwen/Qwen2.5-3B-Instruct-GGUF",
        "filename": "qwen2.5-3b-instruct-q4_k_m.gguf",
    },
    "larger": {
        # ~4.9GB, noticeably better conversation quality, needs 16GB+ RAM to be comfortable.
        "repo_id": "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
        "filename": "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
    },
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=MODELS.keys(), default="default")
    args = parser.parse_args()

    choice = MODELS[args.model]
    out_dir = os.path.join(os.path.dirname(__file__), "..", "models")
    os.makedirs(out_dir, exist_ok=True)

    print(f"Downloading {choice['filename']} from {choice['repo_id']} ...")
    path = hf_hub_download(
        repo_id=choice["repo_id"],
        filename=choice["filename"],
        local_dir=out_dir,
    )
    print(f"\nDone: {path}")
    print("Update config/config.yaml -> llm.llama_cpp.model_path to point at this file")
    print("(the default config already points at the 'default' model's path).")


if __name__ == "__main__":
    main()
