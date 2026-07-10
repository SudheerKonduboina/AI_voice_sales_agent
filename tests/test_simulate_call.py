"""Tests for simulate_call.py."""

import os
import sys
from unittest.mock import MagicMock, mock_open, patch

import pytest
from simulate_call import load_config, main


def test_load_config():
    dummy_yaml = "crm:\n  excel_path: leads.xlsx"
    with patch("builtins.open", mock_open(read_data=dummy_yaml)):
        cfg = load_config("config.yaml")
        assert cfg["crm"]["excel_path"] == "leads.xlsx"


@patch("simulate_call.load_config")
@patch("config_validator.validate_config")
@patch("env_validator.validate_environment")
@patch("excel_crm.get_all_leads")
@patch("builtins.open", new_callable=mock_open, read_data="kb_data")
@patch("simulate_call.create_conversation")
@patch("simulate_call.finalize_call")
def test_main_auto_success(
    mock_finalize,
    mock_create_convo,
    mock_open_kb,
    mock_get_leads,
    mock_val_env,
    mock_val_cfg,
    mock_load,
):
    mock_load.return_value = {
        "crm": {"excel_path": "leads.xlsx", "sheet_name": "Leads"},
        "company": {"knowledge_base_path": "kb.md"},
    }
    # Return environment warnings to cover line 72
    mock_val_env.return_value = ["Telemetry warning"]
    mock_get_leads.return_value = [{"lead_id": "L001", "name": "Alice", "phone": "123"}]

    mock_convo = MagicMock()
    mock_convo.ended = False
    # Set side_effect to invoke callback to cover lines 102-103
    mock_convo.agent_opening_line.side_effect = lambda callback=None: (
        callback("Hello") or "Hello" if callback else "Hello"
    )

    turn_count = 0

    # We make respond_to keep ended=False to exhaust AUTO_SCRIPT, covering line 115-116.
    # We also do not call callback for some turns to cover line 135 (streamed=False).
    def respond_side_effect(user_text, callback=None):
        nonlocal turn_count
        turn_count += 1
        if turn_count == 1:
            # Let it stream
            if callback:
                callback("Hi")
        else:
            # Do not call callback to cover line 135
            pass
        return "Hi"

    mock_convo.respond_to.side_effect = respond_side_effect
    mock_create_convo.return_value = mock_convo

    test_args = ["simulate_call.py", "--lead-id", "L001", "--auto", "--config", "config.yaml"]
    with patch.object(sys, "argv", test_args):
        main()
        assert mock_create_convo.called
        assert mock_finalize.called


@patch("simulate_call.load_config")
@patch("config_validator.validate_config")
@patch("env_validator.validate_environment")
@patch("excel_crm.get_all_leads")
@patch("builtins.open", new_callable=mock_open, read_data="kb_data")
@patch("simulate_call.create_conversation")
@patch("simulate_call.finalize_call")
def test_main_manual_input(
    mock_finalize,
    mock_create_convo,
    mock_open_kb,
    mock_get_leads,
    mock_val_env,
    mock_val_cfg,
    mock_load,
):
    mock_load.return_value = {
        "crm": {"excel_path": "leads.xlsx", "sheet_name": "Leads"},
        "company": {"knowledge_base_path": "kb.md"},
    }
    mock_val_env.return_value = []
    mock_get_leads.return_value = [{"lead_id": "L001", "name": "Alice", "phone": "123"}]

    mock_convo = MagicMock()
    mock_convo.ended = False
    mock_convo.agent_opening_line.return_value = "Hello"
    mock_create_convo.return_value = mock_convo

    # Mock inputs: first empty line, second exit command
    inputs = ["", "exit"]
    with patch("builtins.input", side_effect=inputs):
        test_args = ["simulate_call.py", "--lead-id", "L001", "--config", "config.yaml"]
        with patch.object(sys, "argv", test_args):
            main()
            assert mock_create_convo.called


@patch("simulate_call.load_config")
@patch("config_validator.validate_config")
@patch("env_validator.validate_environment")
@patch("excel_crm.get_all_leads")
def test_main_lead_not_found(mock_get_leads, mock_val_env, mock_val_cfg, mock_load):
    mock_load.return_value = {
        "crm": {"excel_path": "leads.xlsx", "sheet_name": "Leads"},
        "company": {"knowledge_base_path": "kb.md"},
    }
    mock_val_env.return_value = []
    mock_get_leads.return_value = [{"lead_id": "L001"}]

    test_args = ["simulate_call.py", "--lead-id", "LXXX"]
    with patch.object(sys, "argv", test_args):
        main()


@patch("simulate_call.load_config")
@patch("config_validator.validate_config")
def test_main_config_error(mock_val_cfg, mock_load):
    from config_validator import ConfigError

    mock_load.return_value = {}
    mock_val_cfg.side_effect = ConfigError("Invalid config")

    test_args = ["simulate_call.py", "--lead-id", "L001"]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1


@patch("simulate_call.load_config")
@patch("config_validator.validate_config")
@patch("env_validator.validate_environment")
def test_main_env_error(mock_val_env, mock_val_cfg, mock_load):
    from env_validator import EnvironmentValidationError

    mock_load.return_value = {}
    mock_val_env.side_effect = EnvironmentValidationError("Missing env file")

    test_args = ["simulate_call.py", "--lead-id", "L001"]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1


def test_simulate_call_main_block():
    py_file = os.path.join("agent", "simulate_call.py")
    with open(py_file, encoding="utf-8") as f:
        code_str = f.read()

    code = compile(code_str, py_file, "exec")
    global_dict = {
        "__name__": "__main__",
        "__file__": py_file,
    }
    with patch("sys.argv", ["simulate_call.py", "--help"]):
        with pytest.raises(SystemExit):
            exec(code, global_dict)
