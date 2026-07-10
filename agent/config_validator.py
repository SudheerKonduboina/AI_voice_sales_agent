"""
config_validator.py -- Startup configuration validation for the AI Voice Sales Agent.
"""

from __future__ import annotations


class ConfigError(ValueError):
    """Raised when configuration is invalid or missing required keys."""

    pass


def validate_config(cfg: dict) -> None:
    """Validate that all required keys are present with valid types and ranges in config.yaml.

    Raises:
        ConfigError: If validation fails.
    """
    if not isinstance(cfg, dict):
        raise ConfigError("Configuration must be a dictionary.")

    # 1. Company config
    company = cfg.get("company")
    if not isinstance(company, dict):
        raise ConfigError("Missing or invalid 'company' section in configuration.")

    for key in ("name", "caller_purpose", "knowledge_base_path"):
        val = company.get(key)
        if not val or not isinstance(val, str):
            raise ConfigError(
                f"Missing or invalid required key 'company.{key}' (must be a non-empty string)."
            )

    # 2. CRM config
    crm = cfg.get("crm")
    if not isinstance(crm, dict):
        raise ConfigError("Missing or invalid 'crm' section in configuration.")

    for key in ("excel_path", "sheet_name"):
        val = crm.get(key)
        if not val or not isinstance(val, str):
            raise ConfigError(
                f"Missing or invalid required key 'crm.{key}' (must be a non-empty string)."
            )

    # 3. LLM config
    llm = cfg.get("llm")
    if not isinstance(llm, dict):
        raise ConfigError("Missing or invalid 'llm' section in configuration.")

    provider = llm.get("provider")
    if provider not in ("ollama", "llama_cpp", "openai"):
        raise ConfigError(
            "Required key 'llm.provider' must be one of: 'ollama', 'llama_cpp', 'openai'."
        )

    temperature = llm.get("temperature")
    if not isinstance(temperature, (int, float)) or not (0.0 <= temperature <= 2.0):
        raise ConfigError("Required key 'llm.temperature' must be a float/int between 0.0 and 2.0.")

    max_history_turns = llm.get("max_history_turns")
    if not isinstance(max_history_turns, int) or not (1 <= max_history_turns <= 20):
        raise ConfigError(
            "Required key 'llm.max_history_turns' must be an integer between 1 and 20."
        )

    # 4. RAG config
    rag = cfg.get("rag")
    if not isinstance(rag, dict):
        raise ConfigError("Missing or invalid 'rag' section in configuration.")

    top_k = rag.get("top_k")
    if not isinstance(top_k, int) or not (1 <= top_k <= 10):
        raise ConfigError("Required key 'rag.top_k' must be an integer between 1 and 10.")

    min_score = rag.get("min_score")
    if not isinstance(min_score, (int, float)) or not (0.0 <= min_score <= 1.0):
        raise ConfigError("Required key 'rag.min_score' must be a float between 0.0 and 1.0.")

    # 5. Call limits
    call = cfg.get("call")
    if not isinstance(call, dict):
        raise ConfigError("Missing or invalid 'call' section in configuration.")

    for key in ("max_call_duration_seconds", "max_silence_seconds"):
        val = call.get(key)
        if not isinstance(val, (int, float)) or val <= 0:
            raise ConfigError(f"Required key 'call.{key}' must be a positive number.")
