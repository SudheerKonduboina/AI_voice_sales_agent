"""
call_service.py -- shared call orchestration for simulator, API, and batch runner.
"""

from __future__ import annotations

import os
from datetime import datetime

import excel_crm
from analytics import CallMetrics, get_analytics
from conversation import Conversation, ConversationResult
from logger_setup import get_logger

logger = get_logger(__name__)


def create_conversation(lead: dict, cfg: dict, knowledge_base: str, base_dir: str) -> Conversation:
    """Build a Conversation with config-driven memory, RAG, and tools."""
    excel_path = os.path.join(base_dir, cfg["crm"]["excel_path"])
    return Conversation(
        lead=lead,
        company_name=cfg["company"]["name"],
        caller_purpose=cfg["company"]["caller_purpose"],
        knowledge_base=knowledge_base,
        llm_config=cfg["llm"],
        max_turns=cfg["llm"]["max_history_turns"],
        rag_config=cfg.get("rag", {}),
        excel_path=excel_path,
        sheet_name=cfg["crm"]["sheet_name"],
    )


def run_scripted_call(convo: Conversation, script: list[str]) -> ConversationResult:
    """Run a conversation using a scripted list of prospect replies."""
    convo.agent_opening_line()
    for line in script:
        if convo.ended:
            break
        convo.respond_to(line)
    return convo.extract_result()


def finalize_call(
    lead: dict,
    convo: Conversation,
    result: ConversationResult,
    cfg: dict,
    base_dir: str,
) -> ConversationResult:
    """Write CRM update and record analytics."""
    excel_path = os.path.join(base_dir, cfg["crm"]["excel_path"])
    excel_crm.update_lead(
        excel_path,
        lead["lead_id"],
        result.as_update_dict(),
        cfg["crm"]["sheet_name"],
    )
    if convo.tool_executor:
        convo.tool_executor._pending_updates.clear()

    if cfg.get("analytics", {}).get("enabled", True):
        duration = (datetime.now() - convo.started_at).total_seconds()
        retrieval_count = convo.turns  # one retrieval per turn after opening
        analytics_dir = cfg.get("analytics", {}).get("report_dir", "logs/analytics")
        if not os.path.isabs(analytics_dir):
            analytics_dir = os.path.join(base_dir, analytics_dir)
        get_analytics(analytics_dir).record_call(
            CallMetrics(
                lead_id=lead["lead_id"],
                lead_name=lead.get("name", ""),
                status=result.status,
                qualification=result.qualification,
                duration_seconds=round(duration, 2),
                inference_time_seconds=round(convo.total_usage.inference_ms / 1000, 3),
                prompt_tokens=convo.total_usage.prompt_tokens,
                completion_tokens=convo.total_usage.completion_tokens,
                retrieval_count=retrieval_count,
                objections=result.objections_raised,
                meeting_booked=bool(result.meeting_datetime) or result.status == "Booked",
            )
        )

    logger.info(
        "Call finalized lead=%s status=%s conv_id=%s",
        lead["lead_id"],
        result.status,
        getattr(convo, "conv_id", "-"),
    )
    return result
