"""Tests for logger_setup.py."""

import importlib
import logging
import sys
from unittest.mock import patch

import logger_setup
from logger_setup import (
    JsonFormatter,
    clear_conversation_context,
    get_conversation_context,
    get_logger,
    log_exception,
    next_conversation_id,
    next_request_id,
    set_conversation_context,
)


def test_logger_setup_ose_on_config_load():
    # Only raise OSError when opening config.yaml
    orig_open = open

    def conditional_open(file, *args, **kwargs):
        if "config.yaml" in str(file):
            raise OSError("Read error")
        return orig_open(file, *args, **kwargs)

    with patch("builtins.open", conditional_open):
        importlib.reload(logger_setup)


def test_logger_name_matching():
    # Call get_logger with a name starting with "agent" to cover line 222
    logger1 = get_logger("agent")
    assert logger1.name == "agent"

    logger2 = get_logger("agent.sub")
    assert logger2.name == "agent.sub"

    logger3 = get_logger("other")
    assert logger3.name == "agent.other"


def test_conversation_context_helpers():
    # Test set, get, and clear conversation context helpers to cover lines 71-72, 77-80
    set_conversation_context("C123", "L456")
    c_id, l_id = get_conversation_context()
    assert c_id == "C123"
    assert l_id == "L456"

    clear_conversation_context()
    c_id, l_id = get_conversation_context()
    assert c_id is None
    assert l_id is None

    # Run clear again to cover cases where keys are already deleted
    clear_conversation_context()


def test_logger_regex_extract_and_format():
    formatter = JsonFormatter()

    # Test message with [REQ-XXXX] and trailing space
    record1 = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="[REQ-1234] Test message with space",
        args=(),
        exc_info=None,
    )

    from logger_setup import ConversationContextFilter

    filter_obj = ConversationContextFilter()
    filter_obj.filter(record1)

    assert getattr(record1, "req_id", None) == "REQ-1234"
    formatted1 = formatter.format(record1)
    assert "Test message with space" in formatted1
    assert "REQ-1234" in formatted1

    # Test message with [REQ-XXXX] and no trailing space
    record2 = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="[REQ-5678]Test message without space",
        args=(),
        exc_info=None,
    )
    filter_obj.filter(record2)
    assert getattr(record2, "req_id", None) == "REQ-5678"

    formatted2 = formatter.format(record2)
    assert "Test message without space" in formatted2
    assert "REQ-5678" in formatted2


def test_logger_format_exception():
    formatter = JsonFormatter()
    try:
        raise ValueError("Oops exception details")
    except ValueError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname="test.py",
        lineno=10,
        msg="Error msg",
        args=(),
        exc_info=exc_info,
    )
    formatted = formatter.format(record)
    assert "exception" in formatted
    assert "ValueError: Oops exception details" in formatted


def test_log_exception():
    logger = get_logger("agent.test_exc")
    with patch.object(logger, "error") as mock_error:
        log_exception(logger, "An error occurred", ValueError("Invalid state"))
        mock_error.assert_called_once()


def test_request_and_conversation_ids():
    req_id = next_request_id()
    assert req_id.startswith("REQ-")

    conv_id = next_conversation_id()
    assert conv_id.startswith("CALL-")
