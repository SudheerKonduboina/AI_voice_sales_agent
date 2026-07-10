"""
logger_setup.py -- centralized logging configuration for the AI Voice Sales Agent.

Provides:
  - Console handler (INFO level, concise format)
  - Rotating file handlers: agent.log (all levels), errors.log (ERROR+ only)
  - Rotating structured file handler: agent_structured.log (JSON format)
  - Conversation context management (Conversation ID + Lead ID)
  - Request ID generation for tracing individual LLM calls
  - Structured log formatting with timestamps
  - Exception logging helper with stack traces
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_BASE_DIR = Path(__file__).resolve().parent.parent
_LOGS_DIR = _BASE_DIR / "logs"
_LOGS_DIR.mkdir(parents=True, exist_ok=True)

_CONFIG_PATH = _BASE_DIR / "config" / "config.yaml"


def _load_logging_config() -> dict:
    """Load logging settings from config.yaml with safe defaults."""
    defaults = {
        "console_level": "INFO",
        "file_level": "DEBUG",
        "error_level": "ERROR",
        "max_bytes": 5_242_880,  # 5 MB
        "backup_count": 5,
    }
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return {**defaults, **cfg.get("logging", {})}
    except OSError:
        return defaults


_LOG_CFG = _load_logging_config()

_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

# ---------------------------------------------------------------------------
# Conversation Context (Thread-local)
# ---------------------------------------------------------------------------
_context = threading.local()


def set_conversation_context(conv_id: str, lead_id: str) -> None:
    """Set thread-local context variables for the current conversation."""
    _context.conv_id = conv_id
    _context.lead_id = lead_id


def clear_conversation_context() -> None:
    """Clear thread-local conversation context."""
    if hasattr(_context, "conv_id"):
        del _context.conv_id
    if hasattr(_context, "lead_id"):
        del _context.lead_id


def get_conversation_context() -> tuple[str | None, str | None]:
    """Retrieve current conversation context from thread-local storage."""
    conv_id = getattr(_context, "conv_id", None)
    lead_id = getattr(_context, "lead_id", None)
    return conv_id, lead_id


_REQ_PATTERN = re.compile(r"^\[(REQ-\d{4})\]")


class ConversationContextFilter(logging.Filter):
    """Filter that injects conv_id, lead_id, and extracts req_id from logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        conv_id, lead_id = get_conversation_context()
        record.conv_id = conv_id or "-"
        record.lead_id = lead_id or "-"

        # Auto-extract req_id from message prefix if not explicitly set
        if not hasattr(record, "req_id") or record.req_id == "-":
            record.req_id = "-"
            if isinstance(record.msg, str):
                match = _REQ_PATTERN.match(record.msg)
                if match:
                    record.req_id = match.group(1)
        return True


class JsonFormatter(logging.Formatter):
    """Formatter that outputs structured JSON logs for machine readability."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()

        # Clean the message of the [REQ-XXXX] prefix if it's already structured
        clean_msg = message
        req_id = getattr(record, "req_id", "-")
        if req_id != "-":
            prefix = f"[{req_id}] "
            if clean_msg.startswith(prefix):
                clean_msg = clean_msg[len(prefix) :]
            elif clean_msg.startswith(f"[{req_id}]"):
                clean_msg = clean_msg[len(f"[{req_id}]") :]

        log_entry = {
            "ts": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "module": record.module,
            "message": clean_msg,
            "conv_id": getattr(record, "conv_id", "-"),
            "lead_id": getattr(record, "lead_id", "-"),
            "req_id": req_id,
        }

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------
_CONSOLE_FMT = logging.Formatter(
    fmt="%(asctime)s  %(levelname)-7s  [%(conv_id)s] [%(req_id)s]  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
_FILE_FMT = logging.Formatter(
    fmt="%(asctime)s  %(levelname)-7s  [%(conv_id)s] [%(req_id)s]  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ---------------------------------------------------------------------------
# Shared handlers (created once, reused by root agent logger)
# ---------------------------------------------------------------------------
_filter = ConversationContextFilter()

_console_handler = logging.StreamHandler()
_console_handler.setLevel(_LEVEL_MAP.get(_LOG_CFG["console_level"], logging.INFO))
_console_handler.setFormatter(_CONSOLE_FMT)
_console_handler.addFilter(_filter)

_file_handler = RotatingFileHandler(
    _LOGS_DIR / "agent.log",
    maxBytes=int(_LOG_CFG["max_bytes"]),
    backupCount=int(_LOG_CFG["backup_count"]),
    encoding="utf-8",
)
_file_handler.setLevel(_LEVEL_MAP.get(_LOG_CFG["file_level"], logging.DEBUG))
_file_handler.setFormatter(_FILE_FMT)
_file_handler.addFilter(_filter)

_error_handler = RotatingFileHandler(
    _LOGS_DIR / "errors.log",
    maxBytes=int(_LOG_CFG["max_bytes"]),
    backupCount=int(_LOG_CFG["backup_count"]),
    encoding="utf-8",
)
_error_handler.setLevel(_LEVEL_MAP.get(_LOG_CFG["error_level"], logging.ERROR))
_error_handler.setFormatter(_FILE_FMT)
_error_handler.addFilter(_filter)

_structured_handler = RotatingFileHandler(
    _LOGS_DIR / "agent_structured.log",
    maxBytes=int(_LOG_CFG["max_bytes"]),
    backupCount=int(_LOG_CFG["backup_count"]),
    encoding="utf-8",
)
_structured_handler.setLevel(logging.DEBUG)
_structured_handler.setFormatter(JsonFormatter())
_structured_handler.addFilter(_filter)

_handlers_initialized = False


def _ensure_handlers() -> None:
    """Attach shared handlers to the root agent logger once at import time."""
    global _handlers_initialized
    if _handlers_initialized:
        return
    bootstrap = logging.getLogger("agent")
    if not bootstrap.handlers:
        bootstrap.setLevel(logging.DEBUG)
        bootstrap.addHandler(_console_handler)
        bootstrap.addHandler(_file_handler)
        bootstrap.addHandler(_error_handler)
        bootstrap.addHandler(_structured_handler)
        bootstrap.propagate = False
        bootstrap.info("Logging initialized -- logs dir: %s", _LOGS_DIR)
    _handlers_initialized = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger pre-wired with console + rotating file handlers."""
    _ensure_handlers()
    # Normalize name to be nested under 'agent' parent logger
    if not name.startswith("agent") and name != "agent":
        logger_name = f"agent.{name}"
    else:
        logger_name = name
    logger = logging.getLogger(logger_name)
    # Remove any local handlers to ensure only parent logger handles output
    logger.handlers.clear()
    logger.propagate = True
    return logger


def log_exception(logger: logging.Logger, message: str, *args) -> None:
    """Log an exception with full stack trace to agent.log and errors.log."""
    logger.error(message, *args, exc_info=True)


# ---------------------------------------------------------------------------
# Request/Conversation ID generators -- thread-safe
# ---------------------------------------------------------------------------
_req_counter = 0
_req_lock = threading.Lock()

_conv_counter = 0
_conv_lock = threading.Lock()


def next_request_id() -> str:
    """Return a unique request ID like ``REQ-0001``."""
    global _req_counter
    with _req_lock:
        _req_counter += 1
        return f"REQ-{_req_counter:04d}"


def next_conversation_id() -> str:
    """Return a unique conversation ID like ``CALL-YYYYMMDD-0001``."""
    global _conv_counter
    with _conv_lock:
        _conv_counter += 1
        date_str = datetime.now().strftime("%Y%m%d")
        return f"CALL-{date_str}-{_conv_counter:04d}"
