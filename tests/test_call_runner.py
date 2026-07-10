"""Tests for call_runner.py."""

import os
import sys
from unittest.mock import MagicMock, mock_open, patch

import pytest
from call_runner import load_config, main, process_lead


def test_load_config():
    dummy_yaml = "crm:\n  excel_path: leads.xlsx"
    with patch("builtins.open", mock_open(read_data=dummy_yaml)):
        cfg = load_config("config.yaml")
        assert cfg["crm"]["excel_path"] == "leads.xlsx"


@patch("voice_pipeline.run_call")
@patch("call_runner.finalize_call")
def test_process_lead_live(mock_finalize, mock_run_call, temp_excel):
    mock_convo = MagicMock()
    mock_result = MagicMock()
    mock_result.as_update_dict.return_value = {"status": "Called"}
    mock_convo.extract_result.return_value = mock_result
    mock_run_call.return_value = mock_convo

    lead = {"lead_id": "L001"}
    cfg = {
        "crm": {"excel_path": temp_excel, "sheet_name": "Leads"},
        "analytics": {"enabled": False},
    }

    async def mock_run_call_impl(*args):
        return mock_convo

    mock_run_call.side_effect = mock_run_call_impl

    res = process_lead(lead, cfg, "knowledge_base", "live")
    assert res == {"status": "Called"}


@patch("call_runner.create_conversation")
@patch("call_runner.run_scripted_call")
@patch("call_runner.finalize_call")
def test_process_lead_simulate(mock_finalize, mock_run_script, mock_create_convo, temp_excel):
    mock_convo = MagicMock()
    mock_result = MagicMock()
    mock_result.as_update_dict.return_value = {"status": "Booked"}
    mock_run_script.return_value = mock_result

    lead = {"lead_id": "L001"}
    cfg = {
        "crm": {"excel_path": temp_excel, "sheet_name": "Leads"},
        "company": {"name": "Test Co", "caller_purpose": "demo"},
        "llm": {"max_history_turns": 4},
        "analytics": {"enabled": False},
    }

    res = process_lead(lead, cfg, "knowledge_base", "simulate")
    assert res == {"status": "Booked"}


@patch("call_runner.load_config")
@patch("config_validator.validate_config")
@patch("env_validator.validate_environment")
@patch("builtins.open", new_callable=mock_open, read_data="knowledge_base_data")
@patch("excel_crm.get_pending_leads")
@patch("call_runner.process_lead")
def test_main_success(
    mock_process, mock_get_pending, mock_open_kb, mock_val_env, mock_val_cfg, mock_load
):
    mock_load.return_value = {
        "crm": {"excel_path": "leads.xlsx", "sheet_name": "Leads"},
        "company": {"knowledge_base_path": "kb.md"},
    }
    mock_val_env.return_value = ["Warning: Ollama offline"]
    mock_get_pending.return_value = [{"lead_id": "L001", "name": "Alice", "phone": "123"}]
    mock_process.return_value = {"status": "Booked"}

    test_args = ["call_runner.py", "--mode", "simulate", "--config", "config.yaml"]
    with patch.object(sys, "argv", test_args):
        main()
        assert mock_process.called


@patch("call_runner.load_config")
@patch("config_validator.validate_config")
def test_main_config_error(mock_val_cfg, mock_load):
    from config_validator import ConfigError

    mock_load.return_value = {}
    mock_val_cfg.side_effect = ConfigError("Invalid keys")

    test_args = ["call_runner.py"]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1


@patch("call_runner.load_config")
@patch("config_validator.validate_config")
@patch("env_validator.validate_environment")
def test_main_env_error(mock_val_env, mock_val_cfg, mock_load):
    from env_validator import EnvironmentValidationError

    mock_load.return_value = {}
    mock_val_env.side_effect = EnvironmentValidationError("Missing file")

    test_args = ["call_runner.py"]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1


@patch("call_runner.load_config")
@patch("config_validator.validate_config")
@patch("env_validator.validate_environment")
@patch("builtins.open", new_callable=mock_open, read_data="kb")
@patch("excel_crm.get_pending_leads")
@patch("call_runner.process_lead")
@patch("excel_crm.update_lead")
def test_main_process_lead_failure(
    mock_update, mock_process, mock_get_pending, mock_open_kb, mock_val_env, mock_val_cfg, mock_load
):
    mock_load.return_value = {
        "crm": {"excel_path": "leads.xlsx", "sheet_name": "Leads"},
        "company": {"knowledge_base_path": "kb.md"},
    }
    mock_val_env.return_value = []
    mock_get_pending.return_value = [{"lead_id": "L001", "name": "Alice", "phone": "123"}]
    mock_process.side_effect = Exception("Pipeline crashed")

    test_args = ["call_runner.py"]
    with patch.object(sys, "argv", test_args):
        main()
        assert mock_update.called


def test_call_runner_main_block():
    # Read call_runner.py and execute it with __name__ set to "__main__"
    # to hit the main() execution branch and print coverage
    py_file = os.path.join("agent", "call_runner.py")
    with open(py_file, encoding="utf-8") as f:
        code_str = f.read()

    code = compile(code_str, py_file, "exec")
    global_dict = {
        "__name__": "__main__",
        "__file__": py_file,
    }
    # Help flag argparse parsing triggers SystemExit inside main block
    with patch("sys.argv", ["call_runner.py", "--help"]):
        with pytest.raises(SystemExit):
            exec(code, global_dict)
