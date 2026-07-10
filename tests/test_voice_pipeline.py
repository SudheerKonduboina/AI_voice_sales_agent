"""Tests for voice_pipeline.py."""

import asyncio
import os
import sys
from unittest.mock import MagicMock, patch

from conversation import Conversation
from llm_client import LLMUsage
from voice_pipeline import (
    OllamaLLMProcessor,
    SimulatedSTT,
    SimulatedTTS,
    VoiceMetrics,
    run_call,
    run_simulated_voice_call,
)


def test_simulated_stt():
    async def _run():
        stt = SimulatedSTT(["line1", "line2"], latency_ms=10.0)
        res1 = await stt.transcribe()
        assert res1 == "line1"
        res2 = await stt.transcribe()
        assert res2 == "line2"
        res3 = await stt.transcribe()
        assert res3 is None

    asyncio.run(_run())


def test_simulated_tts():
    async def _run():
        tts = SimulatedTTS(latency_ms=10.0)
        with patch("voice_pipeline.logger.info") as mock_info:
            await tts.speak("hello world")
            assert mock_info.called

    asyncio.run(_run())


def test_llm_processor():
    async def _run():
        mock_convo = MagicMock()
        mock_convo.respond_to.return_value = "Assistant response"
        metrics = VoiceMetrics()

        processor = OllamaLLMProcessor(mock_convo, metrics)
        reply = await processor.handle_transcription("Prospect utterance")
        assert reply == "Assistant response"
        assert len(metrics.llm_latency_ms) == 1

        # Test cancellation
        processor.cancel()
        assert processor._cancelled is True
        assert metrics.cancelled is True
        reply_after_cancel = await processor.handle_transcription("utterance 2")
        assert reply_after_cancel == ""

    asyncio.run(_run())


def test_run_simulated_voice_call(sample_config, sample_kb):
    async def _run():
        lead = {"lead_id": "L001", "name": "Alice"}
        cfg = {
            **sample_config,
            "call": {
                "max_silence_seconds": 1.0,
                "max_call_duration_seconds": 2.0,
            },
        }

        with patch("llm_client.chat_with_usage") as mock_chat_usage:
            mock_chat_usage.return_value = (
                "Hello, how can I help?",
                LLMUsage(prompt_tokens=5, completion_tokens=10, inference_ms=50.0),
            )

            convo, metrics = await run_simulated_voice_call(
                lead, cfg, sample_kb, base_dir=".", script=["yes", "spreadsheet"]
            )
            assert isinstance(convo, Conversation)
            assert len(metrics.stt_latency_ms) > 0

    asyncio.run(_run())


def test_run_simulated_voice_call_duration_limit(sample_config, sample_kb):
    async def _run():
        lead = {"lead_id": "L001", "name": "Alice"}
        cfg = {
            **sample_config,
            "call": {
                "max_silence_seconds": 5.0,
                "max_call_duration_seconds": 0.01,
            },
        }

        with patch("llm_client.chat_with_usage") as mock_chat_usage:
            mock_chat_usage.return_value = (
                "Opening line",
                LLMUsage(prompt_tokens=5, completion_tokens=5, inference_ms=10.0),
            )

            convo, metrics = await run_simulated_voice_call(
                lead, cfg, sample_kb, base_dir=".", script=["yes"]
            )
            assert convo.ended is True

    asyncio.run(_run())


def test_run_simulated_voice_call_silence_timeout(sample_config, sample_kb):
    async def _run():
        lead = {"lead_id": "L001", "name": "Alice"}
        cfg = {
            **sample_config,
            "call": {
                "max_silence_seconds": 0.01,
                "max_call_duration_seconds": 10.0,
            },
        }

        with patch("llm_client.chat_with_usage") as mock_chat_usage:
            mock_chat_usage.return_value = (
                "Opening",
                LLMUsage(prompt_tokens=5, completion_tokens=5, inference_ms=10.0),
            )

            # Pass [None, None] to trigger two silences, which exceeds max_silence threshold
            convo, metrics = await run_simulated_voice_call(
                lead, cfg, sample_kb, base_dir=".", script=[None, None]
            )
            assert metrics.silence_timeouts > 0

    asyncio.run(_run())


def test_run_call_fallback_to_simulation(sample_config, sample_kb):
    async def _run():
        lead = {"lead_id": "L001", "name": "Alice"}

        with patch("llm_client.chat_with_usage") as mock_chat_usage:
            mock_chat_usage.return_value = (
                "Hello",
                LLMUsage(prompt_tokens=5, completion_tokens=5, inference_ms=10.0),
            )

            with patch.dict(sys.modules, {"pipecat": None}):
                convo = await run_call(lead, sample_config, sample_kb, base_dir=".")
                assert isinstance(convo, Conversation)

    asyncio.run(_run())


def test_run_call_pipecat_installed(sample_config, sample_kb):
    async def _run():
        lead = {"lead_id": "L001", "name": "Alice"}

        with patch("llm_client.chat_with_usage") as mock_chat_usage:
            mock_chat_usage.return_value = (
                "Hello",
                LLMUsage(prompt_tokens=5, completion_tokens=5, inference_ms=10.0),
            )

            mock_pipecat = MagicMock()
            with patch.dict(sys.modules, {"pipecat": mock_pipecat}):
                convo = await run_call(lead, sample_config, sample_kb, base_dir=".")
                assert isinstance(convo, Conversation)

    asyncio.run(_run())


def test_voice_pipeline_main():
    # Read voice_pipeline.py and execute it with __name__ set to "__main__"
    # to hit the main print statement coverage in the tracked process
    py_file = os.path.join("agent", "voice_pipeline.py")
    with open(py_file, encoding="utf-8") as f:
        code_str = f.read()

    code = compile(code_str, py_file, "exec")
    global_dict = {
        "__name__": "__main__",
        "__file__": py_file,
    }
    with patch("builtins.print") as mock_print:
        exec(code, global_dict)
        assert mock_print.called
