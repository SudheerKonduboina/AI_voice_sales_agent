"""
tests for config_validator.py
"""

import pytest
from config_validator import ConfigError, validate_config


def test_validate_config_valid():
    valid_cfg = {
        "company": {
            "name": "Test Co",
            "caller_purpose": "demo",
            "knowledge_base_path": "config/knowledge_base.md",
        },
        "crm": {"excel_path": "crm/leads_template.xlsx", "sheet_name": "Leads"},
        "llm": {"provider": "ollama", "temperature": 0.5, "max_history_turns": 4},
        "rag": {"top_k": 2, "min_score": 0.01},
        "call": {"max_call_duration_seconds": 300, "max_silence_seconds": 10},
    }
    # Should not raise any error
    validate_config(valid_cfg)


def test_validate_config_not_dict():
    with pytest.raises(ConfigError, match="Configuration must be a dictionary"):
        validate_config("not-a-dict")


def test_validate_config_company_not_dict():
    cfg = {"company": "not-a-dict"}
    with pytest.raises(ConfigError, match="company"):
        validate_config(cfg)


def test_validate_config_missing_keys():
    invalid_cfg = {
        "company": {
            "name": "Test Co"
            # caller_purpose missing
        }
    }
    with pytest.raises(ConfigError) as exc:
        validate_config(invalid_cfg)
    assert "company.caller_purpose" in str(exc.value)


def test_validate_config_crm_not_dict():
    cfg = {
        "company": {
            "name": "Test Co",
            "caller_purpose": "demo",
            "knowledge_base_path": "config/knowledge_base.md",
        },
        "crm": "not-a-dict",
    }
    with pytest.raises(ConfigError, match="crm"):
        validate_config(cfg)


def test_validate_config_crm_invalid_keys():
    cfg = {
        "company": {
            "name": "Test Co",
            "caller_purpose": "demo",
            "knowledge_base_path": "config/knowledge_base.md",
        },
        "crm": {"excel_path": 123, "sheet_name": "Leads"},
    }
    with pytest.raises(ConfigError, match="crm.excel_path"):
        validate_config(cfg)


def test_validate_config_llm_not_dict():
    cfg = {
        "company": {
            "name": "Test Co",
            "caller_purpose": "demo",
            "knowledge_base_path": "config/knowledge_base.md",
        },
        "crm": {"excel_path": "crm/leads_template.xlsx", "sheet_name": "Leads"},
        "llm": "not-a-dict",
    }
    with pytest.raises(ConfigError, match="llm"):
        validate_config(cfg)


def test_validate_config_invalid_provider():
    cfg = {
        "company": {
            "name": "Test Co",
            "caller_purpose": "demo",
            "knowledge_base_path": "config/knowledge_base.md",
        },
        "crm": {"excel_path": "crm/leads_template.xlsx", "sheet_name": "Leads"},
        "llm": {
            "provider": "invalid_provider",  # invalid
            "temperature": 0.5,
            "max_history_turns": 4,
        },
    }
    with pytest.raises(ConfigError) as exc:
        validate_config(cfg)
    assert "llm.provider" in str(exc.value)


def test_validate_config_invalid_temperature():
    cfg = {
        "company": {
            "name": "Test Co",
            "caller_purpose": "demo",
            "knowledge_base_path": "config/knowledge_base.md",
        },
        "crm": {"excel_path": "crm/leads_template.xlsx", "sheet_name": "Leads"},
        "llm": {
            "provider": "openai",
            "temperature": 3.0,  # out of bounds (0-2)
            "max_history_turns": 4,
        },
    }
    with pytest.raises(ConfigError) as exc:
        validate_config(cfg)
    assert "llm.temperature" in str(exc.value)


def test_validate_config_invalid_max_history_turns():
    cfg = {
        "company": {
            "name": "Test Co",
            "caller_purpose": "demo",
            "knowledge_base_path": "config/knowledge_base.md",
        },
        "crm": {"excel_path": "crm/leads_template.xlsx", "sheet_name": "Leads"},
        "llm": {
            "provider": "openai",
            "temperature": 1.0,
            "max_history_turns": "invalid",  # invalid type
        },
    }
    with pytest.raises(ConfigError, match="llm.max_history_turns"):
        validate_config(cfg)


def test_validate_config_rag_not_dict():
    cfg = {
        "company": {
            "name": "Test Co",
            "caller_purpose": "demo",
            "knowledge_base_path": "config/knowledge_base.md",
        },
        "crm": {"excel_path": "crm/leads_template.xlsx", "sheet_name": "Leads"},
        "llm": {"provider": "ollama", "temperature": 0.5, "max_history_turns": 4},
        "rag": "not-a-dict",
    }
    with pytest.raises(ConfigError, match="rag"):
        validate_config(cfg)


def test_validate_config_rag_invalid_top_k():
    cfg = {
        "company": {
            "name": "Test Co",
            "caller_purpose": "demo",
            "knowledge_base_path": "config/knowledge_base.md",
        },
        "crm": {"excel_path": "crm/leads_template.xlsx", "sheet_name": "Leads"},
        "llm": {"provider": "ollama", "temperature": 0.5, "max_history_turns": 4},
        "rag": {"top_k": 20, "min_score": 0.01},  # too large
    }
    with pytest.raises(ConfigError, match="rag.top_k"):
        validate_config(cfg)


def test_validate_config_rag_invalid_min_score():
    cfg = {
        "company": {
            "name": "Test Co",
            "caller_purpose": "demo",
            "knowledge_base_path": "config/knowledge_base.md",
        },
        "crm": {"excel_path": "crm/leads_template.xlsx", "sheet_name": "Leads"},
        "llm": {"provider": "ollama", "temperature": 0.5, "max_history_turns": 4},
        "rag": {"top_k": 2, "min_score": 1.5},  # too large
    }
    with pytest.raises(ConfigError, match="rag.min_score"):
        validate_config(cfg)


def test_validate_config_call_not_dict():
    cfg = {
        "company": {
            "name": "Test Co",
            "caller_purpose": "demo",
            "knowledge_base_path": "config/knowledge_base.md",
        },
        "crm": {"excel_path": "crm/leads_template.xlsx", "sheet_name": "Leads"},
        "llm": {"provider": "ollama", "temperature": 0.5, "max_history_turns": 4},
        "rag": {"top_k": 2, "min_score": 0.01},
        "call": "not-a-dict",
    }
    with pytest.raises(ConfigError, match="call"):
        validate_config(cfg)


def test_validate_config_call_invalid_value():
    cfg = {
        "company": {
            "name": "Test Co",
            "caller_purpose": "demo",
            "knowledge_base_path": "config/knowledge_base.md",
        },
        "crm": {"excel_path": "crm/leads_template.xlsx", "sheet_name": "Leads"},
        "llm": {"provider": "ollama", "temperature": 0.5, "max_history_turns": 4},
        "rag": {"top_k": 2, "min_score": 0.01},
        "call": {"max_call_duration_seconds": -10, "max_silence_seconds": 10},  # negative
    }
    with pytest.raises(ConfigError, match="call.max_call_duration_seconds"):
        validate_config(cfg)
