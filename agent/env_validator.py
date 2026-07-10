"""
env_validator.py -- Environment validation for the AI Voice Sales Agent.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from pathlib import Path


class EnvironmentValidationError(RuntimeError):
    """Raised when environment has fatal issues that prevent execution."""

    pass


def validate_environment(cfg: dict, base_dir: Path) -> list[str]:
    """Validate that files, folders, and configured LLM endpoints are correct and reachable.

    Args:
        cfg: The configuration dictionary.
        base_dir: Path to the root directory of the application.

    Returns:
        List of warning strings.

    Raises:
        EnvironmentValidationError: For fatal issues.
    """
    warnings: list[str] = []

    # 1. Validate logs directory (warn or auto-create)
    logs_dir = base_dir / "logs"
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        warnings.append(f"Failed to create or access logs directory at {logs_dir}: {e}")

    # 2. Validate CRM excel file (fatal)
    excel_path = base_dir / cfg["crm"]["excel_path"]
    if not excel_path.exists():
        raise EnvironmentValidationError(
            f"Excel CRM template not found at '{excel_path}'. "
            "Please ensure you run crm/make_template.py or provide a valid CRM excel file."
        )

    # 3. Validate knowledge base file (fatal)
    kb_path = base_dir / cfg["company"]["knowledge_base_path"]
    if not kb_path.exists():
        raise EnvironmentValidationError(
            f"Knowledge base markdown file not found at '{kb_path}'. "
            "Please check the path company.knowledge_base_path in config.yaml."
        )

    # 4. LLM provider checks
    provider = cfg.get("llm", {}).get("provider", "ollama")

    if provider == "llama_cpp":
        # check GGUF model file exists (fatal)
        cfg_lc = cfg.get("llm", {}).get("llama_cpp", {})
        model_path_str = cfg_lc.get("model_path", "models/qwen2.5-3b-instruct-q4_k_m.gguf")
        model_path = base_dir / model_path_str
        if not model_path.exists():
            raise EnvironmentValidationError(
                f"llama_cpp GGUF model file not found at '{model_path}'. "
                "Please run python scripts/download_model.py or download a GGUF model."
            )

    elif provider == "ollama":
        # check Ollama connection (warning only)
        ollama_url = os.environ.get("OLLAMA_BASE_URL") or cfg.get("llm", {}).get(
            "ollama_base_url", "http://localhost:11434"
        )
        try:
            if not (ollama_url.startswith("http://") or ollama_url.startswith("https://")):
                raise ValueError("Invalid URL scheme")
            req = urllib.request.Request(f"{ollama_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3.0) as resp:  # nosec B310
                if resp.status != 200:
                    warnings.append(
                        f"Ollama server returned status code {resp.status} at {ollama_url}."
                    )
        except Exception as e:
            warnings.append(
                f"Ollama server is unreachable at {ollama_url} (Ollama offline fallback will be active): {e}"
            )

    return warnings
