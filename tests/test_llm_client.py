"""Tests for llm_client.py -- highest risk module."""

import json
import os
import sys
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

# Mock llama_cpp module before importing llm_client
mock_llama_cpp = MagicMock()
sys.modules["llama_cpp"] = mock_llama_cpp

import llm_client  # noqa: E402
from llm_client import LLMError, LLMUsage, extract_json  # noqa: E402


# ---------------------------------------------------------------------------
# extract_json tests
# ---------------------------------------------------------------------------
def test_extract_json_clean():
    raw = '{"status": "Booked", "notes": "follow up"}'
    result = extract_json(raw)
    assert result["status"] == "Booked"


def test_extract_json_with_fences():
    raw = '```json\n{"status": "Pending"}\n```'
    result = extract_json(raw)
    assert result["status"] == "Pending"


def test_extract_json_truncated_repair():
    raw = '{"status": "Booked", "notes": "incomplete'
    result = extract_json(raw)
    assert result["status"] == "Booked"


def test_extract_json_with_preamble():
    raw = 'Here is the result:\n\n{"status": "Called", "notes": "ok"}\n\nDone.'
    result = extract_json(raw)
    assert result["status"] == "Called"


def test_extract_json_nested():
    raw = '{"outer": {"inner": "value"}, "status": "Booked"}'
    result = extract_json(raw)
    assert result["outer"]["inner"] == "value"


def test_extract_json_invalid_raises():
    with pytest.raises(ValueError, match="No JSON"):
        extract_json("This is not JSON at all.")

    with pytest.raises(ValueError, match="No JSON"):
        # Truncated bracket but completely invalid syntax that fails repair
        extract_json('{"status": missing bracket')


# ---------------------------------------------------------------------------
# LLMUsage tests
# ---------------------------------------------------------------------------
def test_llm_usage_iadd():
    u1 = LLMUsage(prompt_tokens=10, completion_tokens=5, inference_ms=100)
    u2 = MagicMock()  # generic test
    u2 = LLMUsage(prompt_tokens=20, completion_tokens=10, inference_ms=200)
    u1 += u2
    assert u1.prompt_tokens == 30
    assert u1.completion_tokens == 15
    assert u1.inference_ms == 300
    assert u1.total_tokens == 45


def test_llm_usage_defaults():
    u = LLMUsage()
    assert u.prompt_tokens == 0
    assert u.completion_tokens == 0
    assert u.inference_ms == 0.0
    assert u.total_tokens == 0


# ---------------------------------------------------------------------------
# LLMError tests
# ---------------------------------------------------------------------------
def test_llm_error_is_runtime_error():
    assert issubclass(LLMError, RuntimeError)
    err = LLMError("test failure")
    assert "test failure" in str(err)


# ---------------------------------------------------------------------------
# chat() function tests (with mocked Ollama)
# ---------------------------------------------------------------------------
def test_chat_ollama_non_streaming():
    """Non-streaming Ollama chat should return the response text."""
    mock_response = json.dumps(
        {
            "message": {"content": "Hello from Ollama"},
            "done": True,
            "prompt_eval_count": 50,
            "eval_count": 20,
            "eval_duration": 500_000_000,  # 500ms in nanoseconds
        }
    ).encode()

    mock_resp = MagicMock()
    mock_resp.read.return_value = mock_response
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = llm_client.chat(
            [{"role": "user", "content": "hi"}],
            {"provider": "ollama", "max_retries": 1, "timeout_secs": 5},
        )
    assert result == "Hello from Ollama"


def test_chat_with_usage_returns_tuple():
    """chat_with_usage should return (text, LLMUsage) tuple."""
    mock_response = json.dumps(
        {
            "message": {"content": "Usage test"},
            "done": True,
            "prompt_eval_count": 100,
            "eval_count": 40,
            "eval_duration": 1_000_000_000,
        }
    ).encode()

    mock_resp = MagicMock()
    mock_resp.read.return_value = mock_response
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        text, usage = llm_client.chat_with_usage(
            [{"role": "user", "content": "hi"}],
            {"provider": "ollama", "max_retries": 1, "timeout_secs": 5},
        )
    assert text == "Usage test"
    assert usage.prompt_tokens == 100
    assert usage.completion_tokens == 40
    assert usage.inference_ms == 1000.0


def test_chat_ollama_raises_llm_error_after_retries():
    """Ollama failures should raise LLMError after max_retries."""

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        with pytest.raises(LLMError):
            llm_client.chat(
                [{"role": "user", "content": "hi"}],
                {"provider": "ollama", "max_retries": 1, "timeout_secs": 1},
            )


# ---------------------------------------------------------------------------
# llama_cpp and openai tests
# ---------------------------------------------------------------------------
def test_chat_llama_cpp_file_not_found():
    """llama_cpp raises FileNotFoundError when model path is invalid."""
    with patch("os.path.exists", return_value=False):
        with pytest.raises(LLMError) as excinfo:
            llm_client.chat(
                [{"role": "user", "content": "hi"}],
                {"provider": "llama_cpp", "llama_cpp": {"model_path": "nonexistent.gguf"}},
            )
        assert isinstance(excinfo.value.__cause__, FileNotFoundError)


def test_chat_llama_cpp_success():
    """llama_cpp successfully returns chat completion response."""
    mock_instance = MagicMock()
    mock_instance.create_chat_completion.return_value = {
        "choices": [{"message": {"content": "Hello from llama_cpp"}}]
    }
    mock_llama_cpp.Llama.return_value = mock_instance

    with patch("os.path.exists", return_value=True):
        # Reset singleton model to trigger load
        llm_client._llama_cpp_model = None
        result = llm_client.chat(
            [{"role": "user", "content": "hi"}],
            {"provider": "llama_cpp", "llama_cpp": {"model_path": "mock.gguf"}},
        )
    assert result == "Hello from llama_cpp"


def test_chat_openai_missing_key():
    """openai provider raises RuntimeError when API key is missing."""
    with patch.dict(os.environ, {}, clear=True):
        if "OPENAI_API_KEY" in os.environ:
            del os.environ["OPENAI_API_KEY"]
        with pytest.raises(LLMError) as excinfo:
            llm_client.chat(
                [{"role": "user", "content": "hi"}],
                {"provider": "openai"},
            )
        assert "OPENAI_API_KEY not set" in str(excinfo.value.__cause__)


def test_chat_openai_success():
    """openai provider returns response from API."""
    mock_response = json.dumps(
        {"choices": [{"message": {"content": "Hello from OpenAI"}}]}
    ).encode()

    mock_resp = MagicMock()
    mock_resp.read.return_value = mock_response
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-mock-key"}):
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = llm_client.chat(
                [{"role": "user", "content": "hi"}],
                {"provider": "openai", "openai_model": "gpt-4o-mini"},
            )
    assert result == "Hello from OpenAI"


# ---------------------------------------------------------------------------
# Offline replies
# ---------------------------------------------------------------------------
def test_offline_reply():
    """Test all code branches in _offline_reply helper."""
    from llm_client import _offline_reply

    # 1. Extraction prompt
    r1 = _offline_reply([{"role": "user", "content": "Extract the outcome as a JSON"}])
    data = json.loads(r1)
    assert data["status"] == "Pending"

    # 2. Not interested
    r2 = _offline_reply([{"role": "user", "content": "I am not interested, thanks"}])
    assert "Have a great day" in r2

    # 3. Pricing
    r3 = _offline_reply([{"role": "user", "content": "How much does it cost?"}])
    assert "$19/user per month" in r3

    # 4. Interest / booking
    r4 = _offline_reply([{"role": "user", "content": "sounds good"}])
    assert "walkthrough" in r4

    # 5. Empty messages
    r5 = _offline_reply([])
    assert "calling on behalf of Acme CRM" in r5

    # 6. Fallback reply
    r6 = _offline_reply([{"role": "user", "content": "Tell me about your product"}])
    assert "currently using to manage leads" in r6


# ---------------------------------------------------------------------------
# New Verification Tests for 100% Coverage
# ---------------------------------------------------------------------------
def test_chat_with_usage_non_ollama_provider():
    """Verify chat_with_usage returns estimated usage for non-Ollama providers."""
    mock_response = json.dumps(
        {"choices": [{"message": {"content": "OpenAI usage reply text"}}]}
    ).encode()

    mock_resp = MagicMock()
    mock_resp.read.return_value = mock_response
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-mock-key"}):
        with patch("urllib.request.urlopen", return_value=mock_resp):
            text, usage = llm_client.chat_with_usage(
                [{"role": "user", "content": "Hi there user"}],
                {"provider": "openai", "openai_model": "gpt-4o-mini"},
            )
    assert text == "OpenAI usage reply text"
    assert usage.prompt_tokens == 12 // 4  # estimation formula: sum(len) // 4
    assert usage.completion_tokens == 22 // 4


def test_chat_with_usage_general_exception_caught():
    """Verify general exceptions are caught and wrapped in LLMError."""
    with patch("llm_client.chat", side_effect=ValueError("Syntax error")):
        with pytest.raises(LLMError, match="LLM call failed"):
            llm_client.chat_with_usage(
                [{"role": "user", "content": "hi"}],
                {"provider": "openai"},
            )


def test_chat_ollama_streaming_mode():
    """Verify streaming response parses chunks and triggers callback."""
    # Chunk stream yield list of bytes lines
    chunk1 = json.dumps({"message": {"content": "Hello "}, "done": False}) + "\n"
    chunk2 = json.dumps({"message": {"content": "world!"}, "done": False}) + "\n"
    chunk3 = (
        json.dumps(
            {
                "done": True,
                "prompt_eval_count": 20,
                "eval_count": 5,
                "eval_duration": 100_000_000,
            }
        )
        + "\n"
    )

    mock_lines = [chunk1.encode(), b"\n", chunk2.encode(), chunk3.encode()]

    mock_resp = MagicMock()
    mock_resp.__iter__ = MagicMock(return_value=iter(mock_lines))
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    callback_outputs = []

    def callback(chunk):
        callback_outputs.append(chunk)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        text, usage = llm_client._chat_ollama(
            [{"role": "user", "content": "hi"}],
            {"provider": "ollama", "stream": True, "timeout_secs": 5},
            "REQ-123",
            callback=callback,
        )
    assert text == "Hello world!"
    assert callback_outputs == ["Hello ", "world!"]
    assert usage.prompt_tokens == 20
    assert usage.completion_tokens == 5
    assert usage.inference_ms == 100.0


def test_chat_ollama_stream_malformed_json_chunk():
    """Verify malformed JSON chunks are ignored during streaming."""
    chunk1 = json.dumps({"message": {"content": "Hello"}, "done": False}) + "\n"
    chunk2 = "invalid json\n"
    chunk3 = json.dumps({"done": True}) + "\n"

    mock_lines = [chunk1.encode(), chunk2.encode(), chunk3.encode()]

    mock_resp = MagicMock()
    mock_resp.__iter__ = MagicMock(return_value=iter(mock_lines))
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        text, _ = llm_client._chat_ollama(
            [{"role": "user", "content": "hi"}],
            {"provider": "ollama", "stream": True},
            "REQ-123",
            callback=lambda x: None,
        )
    assert text == "Hello"


def test_chat_ollama_estimated_tokens_warning():
    """Verify warning is logged if prompt messages are excessively long."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"message": {"content": "ok"}, "done": True}).encode()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        with patch("llm_client.logger.warning") as mock_warn:
            # Create ~13,000 char prompt which is >3,000 tokens
            llm_client.chat(
                [{"role": "user", "content": "a" * 13000}],
                {"provider": "ollama", "max_retries": 1},
            )
            assert mock_warn.called


def test_chat_ollama_timeout_error_retry():
    """Verify TimeoutError raises warning and retries."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(
        {"message": {"content": "retry ok"}, "done": True}
    ).encode()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    side_effects = [TimeoutError("Slow connection"), mock_resp]

    with patch("urllib.request.urlopen", side_effect=side_effects):
        with patch("time.sleep") as mock_sleep:
            result = llm_client.chat(
                [{"role": "user", "content": "hi"}],
                {"provider": "ollama", "max_retries": 2, "timeout_secs": 2},
            )
            assert result == "retry ok"
            mock_sleep.assert_called_once_with(1)


def test_chat_ollama_json_decode_error_retry():
    """Verify JSON decode errors retry and log."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(
        {"message": {"content": "ok json"}, "done": True}
    ).encode()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    # Return invalid JSON response object, then valid response
    bad_resp = MagicMock()
    bad_resp.read.return_value = b"completely invalid json response"
    bad_resp.__enter__ = MagicMock(return_value=bad_resp)
    bad_resp.__exit__ = MagicMock(return_value=False)

    side_effects = [bad_resp, mock_resp]

    with patch("urllib.request.urlopen", side_effect=side_effects):
        with patch("time.sleep") as mock_sleep:
            result = llm_client.chat(
                [{"role": "user", "content": "hi"}],
                {"provider": "ollama", "max_retries": 2},
            )
            assert result == "ok json"


def test_chat_ollama_unexpected_general_exception():
    """Verify unexpected general exception logs and triggers retries."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(
        {"message": {"content": "fallback success"}, "done": True}
    ).encode()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    side_effects = [RuntimeError("Unexpected connection abort"), mock_resp]

    with patch("urllib.request.urlopen", side_effect=side_effects):
        with patch("time.sleep"):
            result = llm_client.chat(
                [{"role": "user", "content": "hi"}],
                {"provider": "ollama", "max_retries": 2},
            )
            assert result == "fallback success"


def test_chat_with_usage_llm_error_re_raised():
    """Verify LLMError raised in chat is re-raised without wrapping."""
    # Using provider="openai" so that chat() is called, triggering our mock side effect
    with patch("llm_client.chat", side_effect=LLMError("Direct LLM failure")):
        with pytest.raises(LLMError, match="Direct LLM failure"):
            llm_client.chat_with_usage([{"role": "user", "content": "hi"}], {"provider": "openai"})


def test_chat_ollama_stream_empty_line():
    """Verify empty lines in stream are skipped successfully (covers line 234)."""
    chunk1 = json.dumps({"message": {"content": "Hi"}, "done": False}) + "\n"
    # Yield empty bytes line
    mock_lines = [chunk1.encode(), b"", b"\n", json.dumps({"done": True}).encode()]

    mock_resp = MagicMock()
    mock_resp.__iter__ = MagicMock(return_value=iter(mock_lines))
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        text, _ = llm_client._chat_ollama(
            [{"role": "user", "content": "hi"}],
            {"provider": "ollama", "stream": True},
            "REQ-123",
            callback=lambda x: None,
        )
    assert text == "Hi"


def test_chat_ollama_stream_json_decode_error_fallback():
    """Verify JSONDecodeError during streaming triggers non-streaming fallback."""
    # We raise JSONDecodeError directly from the generator iterator to enter the outer try-except JSONDecodeError block
    mock_resp = MagicMock()
    mock_resp.__iter__ = MagicMock(side_effect=json.JSONDecodeError("msg", "doc", 0))
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    # Mock non-streaming fallback return value
    fallback_resp = MagicMock()
    fallback_resp.read.return_value = json.dumps(
        {"message": {"content": "fallback success"}, "done": True}
    ).encode()
    fallback_resp.__enter__ = MagicMock(return_value=fallback_resp)
    fallback_resp.__exit__ = MagicMock(return_value=False)

    side_effects = [mock_resp, fallback_resp]

    with patch("urllib.request.urlopen", side_effect=side_effects):
        text, _ = llm_client._chat_ollama(
            [{"role": "user", "content": "hi"}],
            {"provider": "ollama", "stream": True, "stream_fallback": True, "max_retries": 1},
            "REQ-123",
            callback=lambda x: None,
        )
    assert text == "fallback success"


def test_chat_ollama_stream_exception_fallback():
    """Verify raw Exception during streaming triggers non-streaming fallback."""
    mock_resp = MagicMock()
    mock_resp.__iter__ = MagicMock(side_effect=ConnectionResetError("aborted"))
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    # Mock non-streaming fallback return value
    fallback_resp = MagicMock()
    fallback_resp.read.return_value = json.dumps(
        {"message": {"content": "fallback success"}, "done": True}
    ).encode()
    fallback_resp.__enter__ = MagicMock(return_value=fallback_resp)
    fallback_resp.__exit__ = MagicMock(return_value=False)

    side_effects = [mock_resp, fallback_resp]

    with patch("urllib.request.urlopen", side_effect=side_effects):
        text, _ = llm_client._chat_ollama(
            [{"role": "user", "content": "hi"}],
            {"provider": "ollama", "stream": True, "stream_fallback": True, "max_retries": 1},
            "REQ-123",
            callback=lambda x: None,
        )
    assert text == "fallback success"


def test_chat_ollama_stream_exception_fallback_failure():
    """Verify raw Exception during streaming fallback is caught and handled."""
    mock_resp = MagicMock()
    mock_resp.__iter__ = MagicMock(side_effect=ConnectionResetError("aborted"))
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    # Fallback urlopen throws exception too
    side_effects = [mock_resp, RuntimeError("fallback urlopen fails")]

    with patch("urllib.request.urlopen", side_effect=side_effects):
        with pytest.raises(LLMError):
            llm_client._chat_ollama(
                [{"role": "user", "content": "hi"}],
                {"provider": "ollama", "stream": True, "stream_fallback": True, "max_retries": 1},
                "REQ-123",
                callback=lambda x: None,
            )


def test_extract_json_bracket_regex_json_decode_error():
    """Verify that text with curly braces that fails to parse catches JSONDecodeError inside regex block (covers lines 371-372)."""
    # This matches r"\{.*\}" because it has curly braces, but fails to parse because it's not valid JSON,
    # and then goes on to fail repair and raise ValueError.
    with pytest.raises(ValueError) as excinfo:
        extract_json("{invalid json object}")
    assert "No JSON" in str(excinfo.value)


def test_extract_json_repair_failure():
    """Verify json extraction returns ValueError if both normal parse and regex fail."""
    with patch("re.search", return_value=None):
        with pytest.raises(ValueError) as excinfo:
            extract_json("not json")
        assert "No JSON" in str(excinfo.value)


def test_chat_ollama_invalid_url_scheme():
    """Verify _chat_ollama rejects urls with invalid schemes."""
    with pytest.raises(LLMError, match="Invalid URL scheme"):
        llm_client.chat(
            [{"role": "user", "content": "hi"}],
            {"provider": "ollama", "ollama_base_url": "ftp://localhost:11434"},
        )

