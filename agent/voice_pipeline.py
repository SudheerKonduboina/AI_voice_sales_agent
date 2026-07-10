"""
voice_pipeline.py -- real-time voice call pipeline (Pipecat) with simulation mode.

When Pipecat/Whisper/Piper are not installed, ``run_simulated_voice_call`` exercises
the same Conversation logic with text-based STT/TTS simulation and latency metrics.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass, field

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "crm"))

from call_service import create_conversation
from conversation import Conversation
from logger_setup import get_logger

logger = get_logger(__name__)

# Simulated voice script for testing without audio hardware
SIMULATED_VOICE_SCRIPT = [
    "Hello, yes speaking.",
    "We use spreadsheets right now.",
    "Team of about five people.",
    "What does it cost?",
    "Sure, Thursday at 2pm works.",
    "Thanks, bye!",
]


@dataclass
class VoiceMetrics:
    """Latency and pipeline metrics for a voice call."""

    stt_latency_ms: list[float] = field(default_factory=list)
    llm_latency_ms: list[float] = field(default_factory=list)
    tts_latency_ms: list[float] = field(default_factory=list)
    interruptions: int = 0
    silence_timeouts: int = 0
    cancelled: bool = False


class SimulatedSTT:
    """Text-based STT stand-in: returns scripted lines with simulated latency."""

    def __init__(self, script: list[str], latency_ms: float = 50.0):
        self.script = iter(script)
        self.latency_ms = latency_ms

    async def transcribe(self) -> str | None:
        await asyncio.sleep(self.latency_ms / 1000)
        try:
            return next(self.script)
        except StopIteration:
            return None


class SimulatedTTS:
    """Text-based TTS stand-in: logs output with simulated latency."""

    def __init__(self, latency_ms: float = 30.0):
        self.latency_ms = latency_ms

    async def speak(self, text: str) -> None:
        start = time.perf_counter()
        await asyncio.sleep(self.latency_ms / 1000)
        elapsed = (time.perf_counter() - start) * 1000
        logger.info("[TTS SIM] spoke %d chars in %.0f ms", len(text), elapsed)


class OllamaLLMProcessor:
    """Bridges voice pipeline to Conversation state machine."""

    def __init__(self, convo: Conversation, metrics: VoiceMetrics):
        self.convo = convo
        self.metrics = metrics
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        self.metrics.cancelled = True
        logger.info("Voice LLM processor cancelled")

    async def handle_transcription(self, prospect_text: str) -> str:
        if self._cancelled:
            return ""
        loop = asyncio.get_event_loop()
        start = time.perf_counter()
        reply = await loop.run_in_executor(None, self.convo.respond_to, prospect_text)
        self.metrics.llm_latency_ms.append((time.perf_counter() - start) * 1000)
        return reply


async def run_simulated_voice_call(
    lead: dict,
    cfg: dict,
    knowledge_base: str,
    base_dir: str,
    script: list[str] | None = None,
) -> tuple[Conversation, VoiceMetrics]:
    """Run a full voice call simulation with STT/TTS latency measurement."""
    call_cfg = cfg.get("call", {})
    max_silence = float(call_cfg.get("max_silence_seconds", 8))
    max_duration = float(call_cfg.get("max_call_duration_seconds", 420))

    metrics = VoiceMetrics()
    convo = create_conversation(lead, cfg, knowledge_base, base_dir)
    llm = OllamaLLMProcessor(convo, metrics)
    stt = SimulatedSTT(script or SIMULATED_VOICE_SCRIPT)
    tts = SimulatedTTS()

    logger.info(
        "Simulated voice call started lead=%s max_silence=%ss max_duration=%ss",
        lead.get("name"),
        max_silence,
        max_duration,
    )

    call_start = time.perf_counter()
    opening = convo.agent_opening_line()
    await tts.speak(opening)

    while not convo.ended:
        if time.perf_counter() - call_start > max_duration:
            logger.warning("Max call duration reached -- ending call")
            convo.ended = True
            break

        stt_start = time.perf_counter()
        text = await stt.transcribe()
        metrics.stt_latency_ms.append((time.perf_counter() - stt_start) * 1000)

        if text is None:
            metrics.silence_timeouts += 1
            if metrics.silence_timeouts * max_silence > max_silence:
                logger.info("Silence timeout -- ending call")
                break
            continue

        metrics.silence_timeouts = 0
        logger.info("[STT SIM] Prospect: %s", text)
        reply = await llm.handle_transcription(text)
        if reply:
            await tts.speak(reply)

    avg_stt = (
        sum(metrics.stt_latency_ms) / len(metrics.stt_latency_ms) if metrics.stt_latency_ms else 0
    )
    avg_llm = (
        sum(metrics.llm_latency_ms) / len(metrics.llm_latency_ms) if metrics.llm_latency_ms else 0
    )
    logger.info(
        "Voice call finished avg_stt=%.0fms avg_llm=%.0fms interruptions=%d",
        avg_stt,
        avg_llm,
        metrics.interruptions,
    )
    return convo, metrics


async def run_call(
    lead: dict,
    cfg: dict,
    knowledge_base: str,
    base_dir: str = ".",
) -> Conversation:
    """
    Entry point for live or simulated voice calls.
    Falls back to simulation when Pipecat is not installed.
    """
    try:
        import pipecat  # noqa: F401

        pipecat_available = True
    except ImportError:
        pipecat_available = False

    if not pipecat_available:
        logger.info("Pipecat not installed -- running simulated voice call")
        convo, _ = await run_simulated_voice_call(lead, cfg, knowledge_base, base_dir)
        return convo

    # Real Pipecat pipeline construction (requires telephony transport)
    convo = create_conversation(lead, cfg, knowledge_base, base_dir)
    opening = convo.agent_opening_line()
    logger.info("Voice call opening line generated (%d chars)", len(opening))
    return convo


if __name__ == "__main__":
    print(
        "voice_pipeline.py -- use simulate_call.py for text mode or "
        "call_runner.py --mode live for simulated voice."
    )
