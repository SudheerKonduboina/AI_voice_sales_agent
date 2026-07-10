"""
llm_client.py -- LLM backend switcher.

Supports three providers (set via config.yaml -> llm.provider):
  - "llama_cpp": runs a GGUF model IN-PROCESS inside your venv via
    llama-cpp-python. No background service, no system-wide install --
    just a pip package + a model file sitting in models/. This is the
    fully venv-contained option.
  - "ollama": talks to a separately-running Ollama server over HTTP.
  - "openai": talks to the OpenAI API (needs OPENAI_API_KEY).

If none of these are reachable/configured, falls back to a small
rule-based responder so the rest of the pipeline (CRM writes, call flow,
n8n wiring) can still be built, run, and demoed without any LLM at all.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from logger_setup import get_logger, log_exception, next_request_id

logger = get_logger(__name__)


_llama_cpp_model = None  # lazy-loaded singleton -- loading a GGUF file is slow, do it once


class LLMError(RuntimeError):
    """Raised when an LLM call fails after retries."""


@dataclass
class LLMUsage:
    """Token and timing metrics from a single LLM call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    inference_ms: float = 0.0

    def __iadd__(self, other: LLMUsage) -> LLMUsage:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.inference_ms += other.inference_ms
        return self

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def chat(
    messages: list[dict], llm_config: dict, callback: Callable[[str], None] | None = None
) -> str:
    """Send messages to the configured LLM provider and return the response.

    Args:
        messages: List of chat messages with 'role' and 'content' keys.
        llm_config: LLM configuration dict from config.yaml.
        callback: Optional callback function receiving text chunks during streaming.

    Returns:
        The assistant's response text.

    Raises:
        RuntimeError: If the LLM call fails after retries.
    """
    provider = llm_config.get("provider", "ollama")
    req_id = next_request_id()

    logger.info("[%s] Provider=%s", req_id, provider)

    try:
        if provider == "llama_cpp":
            return _chat_llama_cpp(messages, llm_config, req_id)
        elif provider == "openai":
            return _chat_openai(messages, llm_config, req_id)
        else:
            text, _usage = _chat_ollama(messages, llm_config, req_id, callback)
            return text

    except LLMError:
        raise
    except Exception as e:
        log_exception(logger, "[%s] LLM call failed (provider=%s): %s", req_id, provider, e)
        raise LLMError(f"LLM call failed (provider={provider}): {e}") from e


def chat_with_usage(
    messages: list[dict],
    llm_config: dict,
    callback: Callable[[str], None] | None = None,
) -> tuple[str, LLMUsage]:
    """Like chat(), but also returns token usage metrics.

    Currently only populates real usage from Ollama. Other providers return
    estimated usage based on character counts.
    """
    provider = llm_config.get("provider", "ollama")
    req_id = next_request_id()
    logger.info("[%s] Provider=%s (with_usage)", req_id, provider)

    try:
        if provider == "ollama":
            return _chat_ollama(messages, llm_config, req_id, callback)
        else:
            text = chat(messages, llm_config, callback)
            est_prompt = sum(len(m.get("content", "")) for m in messages) // 4
            est_completion = len(text) // 4
            return text, LLMUsage(
                prompt_tokens=est_prompt,
                completion_tokens=est_completion,
                inference_ms=0.0,
            )
    except LLMError:
        raise
    except Exception as e:
        log_exception(logger, "[%s] LLM call failed (provider=%s): %s", req_id, provider, e)
        raise LLMError(f"LLM call failed (provider={provider}): {e}") from e


def _chat_llama_cpp(messages: list[dict], llm_config: dict, req_id: str) -> str:
    """Run inference via llama-cpp-python (in-process GGUF model)."""
    global _llama_cpp_model
    from llama_cpp import Llama  # pip install llama-cpp-python

    cfg = llm_config.get("llama_cpp", {})
    model_path = cfg.get("model_path", "models/qwen2.5-3b-instruct-q4_k_m.gguf")

    if _llama_cpp_model is None:
        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"Model file not found at {model_path!r}. "
                "See docs/SETUP.md 'llama_cpp' section to download one."
            )
        logger.info("[%s] Loading GGUF model from %s", req_id, model_path)
        _llama_cpp_model = Llama(
            model_path=model_path,
            n_ctx=cfg.get("n_ctx", 4096),
            n_threads=cfg.get("n_threads", os.cpu_count() or 4),
            verbose=False,
        )

    start = time.time()
    result = _llama_cpp_model.create_chat_completion(
        messages=messages,
        temperature=llm_config.get("temperature", 0.6),
        max_tokens=cfg.get("max_tokens", 300),
    )
    elapsed = time.time() - start
    logger.info("[%s] llama_cpp inference completed in %.2fs", req_id, elapsed)
    return result["choices"][0]["message"]["content"]


def _chat_ollama(
    messages: list[dict],
    llm_config: dict,
    req_id: str,
    callback: Callable[[str], None] | None = None,
) -> tuple[str, LLMUsage]:
    """Send a chat request to a local Ollama server over HTTP, supporting streaming and callbacks."""
    base_url = os.environ.get("OLLAMA_BASE_URL") or llm_config.get(
        "ollama_base_url", "http://localhost:11434"
    )
    model = llm_config.get("ollama_model", "qwen2.5:3b")
    max_retries = llm_config.get("max_retries", 2)
    timeout_secs = llm_config.get("timeout_secs", 60)
    stream_timeout = llm_config.get("stream_timeout_secs", timeout_secs)
    should_stream = llm_config.get("stream", False) and callback is not None
    stream_fallback = llm_config.get("stream_fallback", True)

    payload = {
        "model": model,
        "messages": messages,
        "stream": should_stream,
        "options": {
            "temperature": llm_config.get("temperature", 0.3),
            "num_ctx": llm_config.get("ollama_num_ctx", 4096),
            "num_predict": llm_config.get("ollama_num_predict", 120),
        },
    }

    payload_json = json.dumps(payload)

    # ---- Metrics ----
    chars = sum(len(m.get("content", "")) for m in messages)
    est_tokens = chars // 4
    logger.info(
        "[%s] Ollama request  model=%s  messages=%d  chars=%d  est_tokens=%d  payload=%d bytes  stream=%s",
        req_id,
        model,
        len(messages),
        chars,
        est_tokens,
        len(payload_json),
        should_stream,
    )
    if est_tokens > 3000:
        logger.warning(
            "[%s] Estimated tokens (%d) > 3000 -- request may be slow or truncated!",
            req_id,
            est_tokens,
        )

    start_time = time.time()

    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        raise ValueError("Invalid URL scheme")

    req = urllib.request.Request(
        f"{base_url}/api/chat",
        data=payload_json.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    effective_timeout = stream_timeout if should_stream else timeout_secs
    usage = LLMUsage()

    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=effective_timeout) as resp:  # nosec B310
                if should_stream:
                    chunks = []
                    last_data = None
                    # Read line-by-line from response stream
                    for line in resp:
                        if not line:
                            continue
                        try:
                            data = json.loads(line.decode("utf-8"))
                            last_data = data
                            chunk = data.get("message", {}).get("content", "")
                            if chunk and callback is not None:
                                chunks.append(chunk)
                                callback(chunk)
                        except json.JSONDecodeError:
                            logger.warning("[%s] Failed to parse stream chunk: %r", req_id, line)
                            continue

                    content = "".join(chunks)
                    elapsed = time.time() - start_time

                    # Extract real token counts from the final Ollama chunk
                    if last_data and last_data.get("done"):
                        usage.prompt_tokens = last_data.get("prompt_eval_count", 0)
                        usage.completion_tokens = last_data.get("eval_count", 0)
                        eval_ns = last_data.get("eval_duration", 0)
                        usage.inference_ms = eval_ns / 1_000_000 if eval_ns else elapsed * 1000

                    resp_tokens = usage.completion_tokens or len(content) // 4
                    logger.info(
                        "[%s] Ollama response (streamed)  attempt=%d  time=%.2fs  resp_chars=%d  tokens=%d",
                        req_id,
                        attempt,
                        elapsed,
                        len(content),
                        resp_tokens,
                    )
                    return content, usage
                else:
                    data = json.loads(resp.read().decode("utf-8"))
                    elapsed = time.time() - start_time
                    content = data["message"]["content"]

                    # Extract real token counts from Ollama response
                    usage.prompt_tokens = data.get("prompt_eval_count", 0)
                    usage.completion_tokens = data.get("eval_count", 0)
                    eval_ns = data.get("eval_duration", 0)
                    usage.inference_ms = eval_ns / 1_000_000 if eval_ns else elapsed * 1000

                    resp_tokens = usage.completion_tokens or len(content) // 4
                    logger.info(
                        "[%s] Ollama response  attempt=%d  time=%.2fs  resp_chars=%d  tokens=%d",
                        req_id,
                        attempt,
                        elapsed,
                        len(content),
                        resp_tokens,
                    )
                    return content, usage
        except TimeoutError:
            logger.warning(
                "[%s] Attempt %d/%d timed out after %ds",
                req_id,
                attempt,
                max_retries,
                effective_timeout,
            )
        except urllib.error.URLError as e:
            logger.warning("[%s] Attempt %d/%d URL error: %s", req_id, attempt, max_retries, e)
        except json.JSONDecodeError as e:
            logger.error(
                "[%s] Attempt %d/%d malformed JSON response: %s", req_id, attempt, max_retries, e
            )
            if should_stream and stream_fallback and callback is not None:
                logger.info("[%s] Streaming failed -- falling back to non-streaming", req_id)
                return _chat_ollama(
                    messages,
                    {**llm_config, "stream": False},
                    req_id,
                    callback=None,
                )
        except Exception as e:
            logger.error("[%s] Attempt %d/%d unexpected error: %s", req_id, attempt, max_retries, e)
            if (
                should_stream
                and stream_fallback
                and callback is not None
                and attempt == max_retries
            ):
                logger.info("[%s] Streaming failed -- falling back to non-streaming", req_id)
                try:
                    return _chat_ollama(
                        messages,
                        {**llm_config, "stream": False},
                        req_id,
                        callback=None,
                    )
                except Exception:  # nosec B110
                    pass

        if attempt < max_retries:
            logger.info("[%s] Retrying in 1s...", req_id)
            time.sleep(1)

    raise LLMError(f"[{req_id}] Ollama request failed after {max_retries} attempts")


def _chat_openai(messages: list[dict], llm_config: dict, req_id: str) -> str:
    """Send a chat request to the OpenAI API."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    model = llm_config.get("openai_model", "gpt-4o-mini")
    payload = {
        "model": model,
        "messages": messages,
        "temperature": llm_config.get("temperature", 0.6),
    }

    start = time.time()
    logger.info("[%s] OpenAI request  model=%s  messages=%d", req_id, model, len(messages))

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:  # nosec B310
        data = json.loads(resp.read())
        elapsed = time.time() - start
        content = data["choices"][0]["message"]["content"]
        logger.info("[%s] OpenAI response  time=%.2fs", req_id, elapsed)
        return content


def extract_json(text: str) -> dict:
    """Pulls the first {...} JSON object out of a model response, tolerating
    stray markdown fences, preamble text, or truncated output."""
    text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()

    # Try the clean path first: find a complete JSON object
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # Repair path: handle truncated JSON (e.g., model hit num_predict limit)
    brace_start = text.find("{")
    if brace_start != -1:
        partial = text[brace_start:]
        # Close any unclosed string
        if partial.count('"') % 2 == 1:
            partial += '"'
        # Close unclosed braces
        open_braces = partial.count("{") - partial.count("}")
        partial += "}" * max(0, open_braces)
        try:
            result = json.loads(partial)
            logger.warning("Parsed truncated JSON after repair (%d chars)", len(partial))
            return result
        except json.JSONDecodeError:
            pass

    raise ValueError(f"No JSON object found in LLM output: {text!r}")


def _offline_reply(messages: list[dict]) -> str:
    """Very small rule-based stand-in for the LLM, used only when no real
    provider is reachable. Good enough to exercise the call flow end-to-end;
    not a substitute for the real model in production."""
    last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    low = last_user.lower()

    if "Extract the outcome as a" in last_user:
        return json.dumps(
            {
                "status": "Pending",
                "qualification": "Warm",
                "conversation_summary": "Offline demo mode: no real LLM call made; this is a stub summary.",
                "customer_requirements": "N/A",
                "objections_raised": "None",
                "follow_up_date": "",
                "meeting_datetime": "",
                "notes": "Generated by offline fallback -- connect a real LLM provider for real extraction.",
            }
        )

    if any(w in low for w in ["not interested", "no thanks", "don't call", "remove me"]):
        return "Understood, I won't take up more of your time -- thanks for hearing me out. Have a great day!"
    if any(w in low for w in ["price", "cost", "how much"]):
        return "Our Starter plan is $19/user per month with a 14-day free trial, no card needed. Want me to send details?"
    if any(w in low for w in ["yes", "sure", "sounds good", "interested", "book", "meeting"]):
        return "Great -- what day and time works best for a quick 15-minute walkthrough this week?"
    if not last_user:
        return "Hi, this is an AI assistant calling on behalf of Acme CRM Solutions -- do you have a quick minute?"
    return "That makes sense -- could you tell me a bit more about what you're currently using to manage leads?"
