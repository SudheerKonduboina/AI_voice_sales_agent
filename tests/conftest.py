"""Shared pytest fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_XLSX = BASE_DIR / "crm" / "leads_template.xlsx"


@pytest.fixture
def sample_kb() -> str:
    return """# Company
## Pricing
Starter plan $19/user/month. Pro plan $39/user/month.

## Features
CRM, calling, meeting scheduling in one platform.

## Integrations
Works with Gmail, Outlook, Slack.
"""


@pytest.fixture
def sample_config() -> dict:
    return {
        "company": {"name": "Test Co", "caller_purpose": "testing"},
        "crm": {"excel_path": "crm/leads_template.xlsx", "sheet_name": "Leads"},
        "llm": {"provider": "ollama", "max_history_turns": 2, "stream": False},
        "rag": {"top_k": 2, "min_score": 0.01, "allow_full_fallback": False},
        "analytics": {"enabled": False},
    }


@pytest.fixture
def temp_analytics_dir(tmp_path):
    return str(tmp_path / "analytics")


@pytest.fixture
def temp_excel(tmp_path):
    """Copy leads_template.xlsx to a temp dir for safe write tests."""
    if not TEMPLATE_XLSX.exists():
        pytest.skip("leads_template.xlsx not found")
    dest = tmp_path / "leads.xlsx"
    shutil.copy2(str(TEMPLATE_XLSX), str(dest))
    return str(dest)


@pytest.fixture
def mock_llm_chat():
    """Patch llm_client.chat to return a fixed string without calling Ollama."""
    with patch("llm_client.chat", return_value="Mock LLM response") as m:
        yield m


@pytest.fixture
def mock_llm_chat_with_usage():
    """Patch llm_client.chat_with_usage to return a fixed (str, LLMUsage) tuple."""
    from llm_client import LLMUsage

    usage = LLMUsage(prompt_tokens=100, completion_tokens=30, inference_ms=250.0)
    with patch("llm_client.chat_with_usage", return_value=("Mock LLM response", usage)) as m:
        yield m


@pytest.fixture
def mock_ollama_unreachable():
    """Patch urllib.request.urlopen to simulate Ollama being unreachable."""
    import urllib.error

    def _raise(*args, **kwargs):
        raise urllib.error.URLError("Connection refused")

    with patch("urllib.request.urlopen", side_effect=_raise) as m:
        yield m
