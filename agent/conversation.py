"""
conversation.py -- conversation state machine used by both the live voice
pipeline (agent/voice_pipeline.py) and the text-mode simulator
(agent/simulate_call.py), so the same logic backs both.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import llm_client
import prompts
from knowledge_retriever import KnowledgeRetriever, RetrievalResult
from llm_client import LLMUsage
from logger_setup import (
    clear_conversation_context,
    get_logger,
    log_exception,
    next_conversation_id,
    set_conversation_context,
)
from memory import CustomerMemory
from tools import ToolExecutor

logger = get_logger(__name__)

END_PHRASES = [
    "have a great day",
    "have a good day",
    "take care",
    "goodbye",
    "bye now",
    "won't take up more of your time",
    "thanks for your time",
]

_TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


@dataclass
class ConversationResult:
    status: str
    qualification: str
    conversation_summary: str
    customer_requirements: str
    objections_raised: str
    follow_up_date: str
    meeting_datetime: str
    notes: str

    def as_update_dict(self) -> dict:
        return {
            "status": self.status,
            "qualification": self.qualification,
            "conversation_summary": self.conversation_summary,
            "customer_requirements": self.customer_requirements,
            "objections_raised": self.objections_raised,
            "follow_up_date": self.follow_up_date,
            "meeting_datetime": self.meeting_datetime,
            "notes": self.notes,
        }


class Conversation:
    """Manages a single sales call with memory, RAG, summarisation, and tools."""

    def __init__(
        self,
        lead: dict,
        company_name: str,
        caller_purpose: str,
        knowledge_base: str,
        llm_config: dict,
        max_turns: int = 4,
        rag_config: dict | None = None,
        excel_path: str | None = None,
        sheet_name: str = "Leads",
    ):
        self.lead = lead
        self.company_name = company_name
        self.caller_purpose = caller_purpose
        self.llm_config = llm_config
        self.max_turns = max_turns
        self.rag_config = rag_config or {}
        self.turns = 0
        self.ended = False
        self.conversation_summary: str = ""
        self.full_transcript: list[dict] = []
        self.memory = CustomerMemory()
        self.last_retrieval: RetrievalResult | None = None
        self._total_usage = LLMUsage()

        self.retriever = KnowledgeRetriever(
            knowledge_base,
            min_score=float(self.rag_config.get("min_score", 0.01)),
            allow_full_fallback=bool(self.rag_config.get("allow_full_fallback", False)),
            cache_size=int(self.rag_config.get("cache_size", 32)),
        )
        self.knowledge_base = knowledge_base

        self.tool_executor: ToolExecutor | None = None
        if excel_path:
            self.tool_executor = ToolExecutor(excel_path, lead["lead_id"], sheet_name)

        self.conv_id = next_conversation_id()
        set_conversation_context(self.conv_id, lead["lead_id"])

        system_prompt = self._build_system_prompt(knowledge_base)
        self.messages: list[dict] = [{"role": "system", "content": system_prompt}]
        self.started_at = datetime.now()
        logger.info(
            "Conversation started lead=%s max_turns=%d tools=%s conv_id=%s prompt_version=%s",
            lead.get("name", "?"),
            max_turns,
            self.tool_executor is not None,
            self.conv_id,
            prompts.get_prompt_version(),
        )

    def _build_system_prompt(self, knowledge_base: str) -> str:
        """Build system prompt preserving summary and persistent customer facts."""
        return prompts.build_system_prompt(
            company_name=self.company_name,
            caller_purpose=self.caller_purpose,
            lead_name=self.lead.get("name", "there"),
            knowledge_base=knowledge_base,
            conversation_summary=self.conversation_summary,
            customer_facts=self.memory.to_prompt_section(),
        )

    def agent_opening_line(self, callback: Callable[[str], None] | None = None) -> str:
        """Generates the agent's first line to kick off the call."""
        reply = self._chat_and_process_tools(callback)
        self.messages.append({"role": "assistant", "content": reply})
        self.full_transcript.append({"role": "assistant", "content": reply})
        self.memory.absorb_turn("assistant", reply)
        logger.info("Opening line generated (%d chars)", len(reply))
        return reply

    def respond_to(self, user_text: str, callback: Callable[[str], None] | None = None) -> str:
        """Feeds prospect speech in, returns the agent's reply."""
        self.messages.append({"role": "user", "content": user_text})
        self.full_transcript.append({"role": "user", "content": user_text})
        self.memory.absorb_turn("user", user_text)
        self.turns += 1

        messages_before = len(self.messages)
        self._trim_history_if_needed()
        self._update_system_prompt_with_rag(user_text)

        reply = self._chat_and_process_tools(callback)
        self.messages.append({"role": "assistant", "content": reply})
        self.full_transcript.append({"role": "assistant", "content": reply})
        self.memory.absorb_turn("assistant", reply)

        if any(phrase in reply.lower() for phrase in END_PHRASES) or self.turns >= self.max_turns:
            self.ended = True
            logger.info(
                "Conversation ended at turn %d (messages %d -> %d after trim)",
                self.turns,
                messages_before,
                len(self.messages),
            )
        return reply

    def _chat_and_process_tools(self, callback: Callable[[str], None] | None = None) -> str:
        """Call LLM, execute any tool calls, return cleaned conversational text."""
        raw, usage = llm_client.chat_with_usage(self.messages, self.llm_config, callback=callback)
        self._total_usage += usage
        reply, tool_results = self._parse_and_execute_tools(raw)

        if tool_results:
            result_text = "\n".join(
                f"[Tool {r.tool_name}: {'OK' if r.success else 'FAILED'} -- {r.message}]"
                for r in tool_results
            )
            self.messages.append({"role": "system", "content": f"Tool results:\n{result_text}"})
            follow_up, follow_usage = llm_client.chat_with_usage(
                self.messages, self.llm_config, callback=callback
            )
            self._total_usage += follow_usage
            reply = self._strip_tool_calls(follow_up)

        return reply

    @property
    def total_usage(self) -> LLMUsage:
        """Accumulated token usage across all LLM calls in this conversation."""
        return self._total_usage

    def _parse_and_execute_tools(self, text: str) -> tuple[str, list]:
        """Extract tool calls from LLM output and execute them."""
        if not self.tool_executor:
            return self._strip_tool_calls(text), []

        results = []
        for match in _TOOL_CALL_PATTERN.finditer(text):
            try:
                payload = json.loads(match.group(1))
                tool_name = payload.get("name", "")
                params = payload.get("parameters", {})
                result = self.tool_executor.execute(tool_name, params)
                results.append(result)
                if result.success and tool_name == "schedule_meeting":
                    self.memory.set_meeting(params.get("datetime", ""))
                elif result.success and tool_name == "add_follow_up":
                    self.memory.set_follow_up(params.get("date", ""))
                logger.info("Tool executed: %s success=%s", tool_name, result.success)
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Malformed tool call ignored: %s", e)

        return self._strip_tool_calls(text), results

    @staticmethod
    def _strip_tool_calls(text: str) -> str:
        """Remove tool_call tags from visible reply text."""
        cleaned = _TOOL_CALL_PATTERN.sub("", text).strip()
        return cleaned or text.strip()

    def _update_system_prompt_with_rag(self, user_text: str) -> None:
        """Rebuild system prompt with relevant KB chunks only."""
        top_k = int(self.rag_config.get("top_k", 2))
        result = self.retriever.retrieve(user_text, top_k=top_k)
        self.last_retrieval = result

        full_kb_chars = len(self.knowledge_base)
        reduction_pct = (
            round((1 - result.retrieved_chars / full_kb_chars) * 100, 1) if full_kb_chars else 0.0
        )
        logger.info(
            "RAG prompt reduction: %d -> %d chars (%.1f%% saved) sections=%s",
            full_kb_chars,
            result.retrieved_chars,
            reduction_pct,
            result.section_titles,
        )

        new_system = self._build_system_prompt(result.text)
        self.messages[0] = {"role": "system", "content": new_system}

    def _trim_history_if_needed(self) -> bool:
        """Keep system prompt + last N turn-pairs; summarise older messages."""
        keep_pairs = int(self.llm_config.get("max_history_turns", self.max_turns))
        keep_messages = 2 * keep_pairs
        if len(self.messages) <= keep_messages + 1:
            return False

        old_messages = self.messages[1:-keep_messages]
        chars_before = sum(len(m.get("content", "")) for m in self.messages)
        self.conversation_summary = self._summarise_messages(old_messages)
        self.messages = [self.messages[0]] + self.messages[-keep_messages:]
        chars_after = sum(len(m.get("content", "")) for m in self.messages)

        logger.info(
            "Summary created: %d old messages -> %d char summary; context %d -> %d chars",
            len(old_messages),
            len(self.conversation_summary),
            chars_before,
            chars_after,
        )
        return True

    def _summarise_messages(self, messages: list[dict]) -> str:
        """Summarise older turns via LLM; preserve meeting facts in memory."""
        transcript_lines = []
        for m in messages:
            speaker = "Agent" if m["role"] == "assistant" else "Prospect"
            transcript_lines.append(f"{speaker}: {m['content']}")
            self.memory.absorb_turn(m["role"], m["content"])
        transcript = "\n".join(transcript_lines)

        summary_prompt = prompts.build_summary_prompt(transcript)
        try:
            summary = llm_client.chat(
                [{"role": "user", "content": summary_prompt}],
                self.llm_config,
            )
            logger.info("Conversation summary generated (%d chars)", len(summary))
            return summary.strip()
        except Exception as e:
            log_exception(logger, "Failed to summarise conversation: %s", e)
            return transcript[:500]

    def transcript_text(self) -> str:
        """Return the full transcript for extraction."""
        lines = []
        for m in self.full_transcript:
            speaker = "Agent" if m["role"] == "assistant" else "Prospect"
            lines.append(f"{speaker}: {m['content']}")
        return "\n".join(lines)

    def extract_result(self) -> ConversationResult:
        """Turn transcript into structured CRM fields, merging tool/memory data."""
        extraction_prompt = prompts.build_extraction_prompt(self.transcript_text())
        extraction_config = {**self.llm_config, "ollama_num_predict": 500}

        data = None
        raw = ""
        for attempt in range(2):
            raw = llm_client.chat(
                [{"role": "user", "content": extraction_prompt}],
                extraction_config,
            )
            try:
                data = llm_client.extract_json(raw)
                logger.info("CRM extraction succeeded on attempt %d", attempt + 1)
                break
            except ValueError as e:
                logger.warning("CRM extraction attempt %d failed: %s", attempt + 1, e)

        if data is None:
            logger.error("CRM extraction failed after all attempts -- using fallback")
            data = {
                "status": "Pending",
                "qualification": "Not Yet Assessed",
                "conversation_summary": "Could not parse call outcome -- needs manual review.",
                "customer_requirements": "",
                "objections_raised": "",
                "follow_up_date": "",
                "meeting_datetime": "",
                "notes": f"Raw LLM output: {raw[:300]}",
            }

        # Never lose meeting details captured during the call
        if self.memory.meeting_datetime and not data.get("meeting_datetime"):
            data["meeting_datetime"] = self.memory.meeting_datetime
            if data.get("status") == "Pending":
                data["status"] = "Booked"
        if self.memory.follow_up_date and not data.get("follow_up_date"):
            data["follow_up_date"] = self.memory.follow_up_date
        if self.memory.requirements and not data.get("customer_requirements"):
            data["customer_requirements"] = "; ".join(self.memory.requirements)
        if self.memory.objections and not data.get("objections_raised"):
            data["objections_raised"] = "; ".join(self.memory.objections)

        result = ConversationResult(
            status=data.get("status", "Pending"),
            qualification=data.get("qualification", "Not Yet Assessed"),
            conversation_summary=data.get("conversation_summary", ""),
            customer_requirements=data.get("customer_requirements", ""),
            objections_raised=data.get("objections_raised", ""),
            follow_up_date=data.get("follow_up_date", ""),
            meeting_datetime=data.get("meeting_datetime", ""),
            notes=data.get("notes", ""),
        )

        if self.tool_executor:
            pending = self.tool_executor.get_pending_updates()
            merged = result.as_update_dict()
            for key, value in pending.items():
                if value and not merged.get(key):
                    merged[key] = value
            result = ConversationResult(**{k: merged.get(k, "") for k in result.as_update_dict()})

        logger.info(
            "Extraction complete conv_id=%s status=%s qualification=%s",
            self.conv_id,
            result.status,
            result.qualification,
        )
        clear_conversation_context()
        return result
