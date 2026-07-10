"""
Tests for env_validator.py
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from env_validator import EnvironmentValidationError, validate_environment


@pytest.fixture
def base_cfg():
    return {
        "crm": {"excel_path": "crm/leads_template.xlsx"},
        "company": {"knowledge_base_path": "config/knowledge_base.md"},
        "llm": {"provider": "ollama", "ollama_base_url": "http://localhost:11434"},
    }


def test_validate_environment_missing_crm(tmp_path, base_cfg):
    # KB path exists but CRM path does not
    kb_dir = tmp_path / "config"
    kb_dir.mkdir()
    kb_file = kb_dir / "knowledge_base.md"
    kb_file.write_text("## Test Section")

    cfg = dict(base_cfg)
    cfg["company"]["knowledge_base_path"] = "config/knowledge_base.md"
    cfg["crm"]["excel_path"] = "crm/leads_template.xlsx"  # does not exist

    with pytest.raises(EnvironmentValidationError) as exc:
        validate_environment(cfg, tmp_path)
    assert "Excel CRM template not found" in str(exc.value)


def test_validate_environment_missing_kb(tmp_path, base_cfg):
    # CRM exists but KB does not
    crm_dir = tmp_path / "crm"
    crm_dir.mkdir()
    crm_file = crm_dir / "leads_template.xlsx"
    crm_file.write_text("dummy excel")

    cfg = dict(base_cfg)
    cfg["company"]["knowledge_base_path"] = "config/knowledge_base.md"  # does not exist
    cfg["crm"]["excel_path"] = "crm/leads_template.xlsx"

    with pytest.raises(EnvironmentValidationError) as exc:
        validate_environment(cfg, tmp_path)
    assert "Knowledge base markdown file not found" in str(exc.value)


@patch("urllib.request.urlopen")
def test_validate_environment_ollama_unreachable(mock_urlopen, tmp_path, base_cfg):
    # Create CRM and KB dummy files
    crm_dir = tmp_path / "crm"
    crm_dir.mkdir()
    (crm_dir / "leads_template.xlsx").write_text("excel")

    kb_dir = tmp_path / "config"
    kb_dir.mkdir()
    (kb_dir / "knowledge_base.md").write_text("kb")

    # Mock urlopen to raise exception (server offline)
    mock_urlopen.side_effect = Exception("Connection refused")

    warnings = validate_environment(base_cfg, tmp_path)
    assert len(warnings) > 0
    assert any("Ollama server is unreachable" in w for w in warnings)


@patch("urllib.request.urlopen")
def test_validate_environment_ollama_non_200(mock_urlopen, tmp_path, base_cfg):
    # Create CRM and KB dummy files
    crm_dir = tmp_path / "crm"
    crm_dir.mkdir()
    (crm_dir / "leads_template.xlsx").write_text("excel")

    kb_dir = tmp_path / "config"
    kb_dir.mkdir()
    (kb_dir / "knowledge_base.md").write_text("kb")

    # Mock urlopen returning a response with status = 500
    mock_resp = MagicMock()
    mock_resp.status = 500
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    warnings = validate_environment(base_cfg, tmp_path)
    assert len(warnings) > 0
    assert any("returned status code 500" in w for w in warnings)


def test_validate_environment_logs_mkdir_fails(tmp_path, base_cfg):
    # Create CRM and KB dummy files
    crm_dir = tmp_path / "crm"
    crm_dir.mkdir()
    (crm_dir / "leads_template.xlsx").write_text("excel")

    kb_dir = tmp_path / "config"
    kb_dir.mkdir()
    (kb_dir / "knowledge_base.md").write_text("kb")

    # Mock mkdir to raise exception
    with patch.object(Path, "mkdir", side_effect=Exception("Permission denied")):
        warnings = validate_environment(base_cfg, tmp_path)
        assert len(warnings) > 0
        assert any("Failed to create or access logs directory" in w for w in warnings)


def test_validate_environment_llama_cpp_missing_model(tmp_path, base_cfg):
    crm_dir = tmp_path / "crm"
    crm_dir.mkdir()
    (crm_dir / "leads_template.xlsx").write_text("excel")

    kb_dir = tmp_path / "config"
    kb_dir.mkdir()
    (kb_dir / "knowledge_base.md").write_text("kb")

    cfg = dict(base_cfg)
    cfg["llm"]["provider"] = "llama_cpp"
    cfg["llm"]["llama_cpp"] = {"model_path": "models/qwen.gguf"}

    with pytest.raises(EnvironmentValidationError) as exc:
        validate_environment(cfg, tmp_path)
    assert "GGUF model file not found" in str(exc.value)


def test_validate_environment_ollama_invalid_scheme(tmp_path, base_cfg):
    crm_dir = tmp_path / "crm"
    crm_dir.mkdir()
    (crm_dir / "leads_template.xlsx").write_text("excel")

    kb_dir = tmp_path / "config"
    kb_dir.mkdir()
    (kb_dir / "knowledge_base.md").write_text("kb")

    cfg = dict(base_cfg)
    cfg["llm"]["provider"] = "ollama"
    cfg["llm"]["ollama_base_url"] = "ftp://localhost:11434"

    warnings = validate_environment(cfg, tmp_path)
    assert len(warnings) > 0
    assert any("Ollama server is unreachable" in w for w in warnings)
