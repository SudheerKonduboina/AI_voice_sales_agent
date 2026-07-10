"""
tools.py -- Function calling registry for the AI Voice Sales Agent.

Instead of letting the LLM hallucinate actions like "I'll book a meeting",
this module provides real Python functions that the conversation logic can
invoke based on LLM output. The LLM signals intent via structured JSON,
and the tool executor dispatches to the correct function.

Usage:
    from tools import ToolExecutor
    executor = ToolExecutor(excel_path, lead_id, sheet_name)
    result = executor.execute("schedule_meeting", {"datetime": "2026-07-14 15:00"})
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "crm"))

from logger_setup import get_logger

logger = get_logger(__name__)

# Tool definitions exposed to the LLM so it knows what it can call
TOOL_DEFINITIONS = [
    {
        "name": "schedule_meeting",
        "description": "Book a meeting with the prospect at a specific date and time.",
        "parameters": {
            "datetime": "Meeting date and time in YYYY-MM-DD HH:MM format",
        },
    },
    {
        "name": "add_follow_up",
        "description": "Schedule a follow-up call on a specific date.",
        "parameters": {
            "date": "Follow-up date in YYYY-MM-DD format",
            "reason": "Brief reason for follow-up",
        },
    },
    {
        "name": "mark_not_interested",
        "description": "Mark the prospect as not interested and record the reason.",
        "parameters": {
            "reason": "Why the prospect declined",
        },
    },
    {
        "name": "save_requirement",
        "description": "Save a specific customer requirement or need mentioned during the call.",
        "parameters": {
            "requirement": "What the customer needs",
        },
    },
    {
        "name": "save_objection",
        "description": "Record an objection raised by the prospect.",
        "parameters": {
            "objection": "The objection text",
        },
    },
    {
        "name": "update_crm",
        "description": "Update CRM fields for the current lead.",
        "parameters": {
            "field": "CRM field name (status, qualification, notes, etc.)",
            "value": "Value to set",
        },
    },
    {
        "name": "mark_qualification",
        "description": "Set lead qualification level.",
        "parameters": {
            "level": "Hot, Warm, Cold, Unqualified, or Not Yet Assessed",
        },
    },
    {
        "name": "save_notes",
        "description": "Append notes about the prospect.",
        "parameters": {
            "note": "Note text to save",
        },
    },
    {
        "name": "send_email",
        "description": "Send a follow-up email (simulation only -- logs but does not send).",
        "parameters": {
            "subject": "Email subject",
            "body": "Email body",
        },
    },
]


@dataclass
class ToolResult:
    """Result of executing a tool function."""

    success: bool
    tool_name: str
    message: str
    data: dict


class ToolExecutor:
    """Dispatches tool calls to real Python functions that update the CRM."""

    def __init__(self, excel_path: str, lead_id: str, sheet_name: str = "Leads"):
        self.excel_path = excel_path
        self.lead_id = lead_id
        self.sheet_name = sheet_name
        self._pending_updates: dict[str, Any] = {}
        self._requirements: list[str] = []
        self._objections: list[str] = []

    def execute(self, tool_name: str, params: dict) -> ToolResult:
        """Execute a tool by name with the given parameters.

        Args:
            tool_name: Name of the tool to execute.
            params: Parameters for the tool.

        Returns:
            ToolResult with success status and message.
        """
        handler = getattr(self, f"_tool_{tool_name}", None)
        if handler is None:
            logger.warning("Unknown tool called: %s", tool_name)
            return ToolResult(
                success=False,
                tool_name=tool_name,
                message=f"Unknown tool: {tool_name}",
                data={},
            )

        try:
            result = handler(params)
            logger.info("Tool '%s' executed successfully: %s", tool_name, result.message)
            return result
        except Exception as e:
            logger.error("Tool '%s' failed: %s", tool_name, e)
            return ToolResult(
                success=False,
                tool_name=tool_name,
                message=f"Tool execution failed: {e}",
                data={},
            )

    def _tool_schedule_meeting(self, params: dict) -> ToolResult:
        """Book a meeting -- updates CRM with meeting datetime and status."""
        meeting_dt = params.get("datetime", "")
        if not meeting_dt:
            return ToolResult(False, "schedule_meeting", "No datetime provided", {})

        self._pending_updates["meeting_datetime"] = meeting_dt
        self._pending_updates["status"] = "Booked"
        self._pending_updates["qualification"] = "Hot"
        logger.info("Meeting scheduled for %s (lead=%s)", meeting_dt, self.lead_id)
        return ToolResult(
            True,
            "schedule_meeting",
            f"Meeting booked for {meeting_dt}",
            {"meeting_datetime": meeting_dt},
        )

    def _tool_add_follow_up(self, params: dict) -> ToolResult:
        """Schedule a follow-up call."""
        follow_date = params.get("date", "")
        reason = params.get("reason", "")
        if not follow_date:
            return ToolResult(False, "add_follow_up", "No date provided", {})

        self._pending_updates["follow_up_date"] = follow_date
        self._pending_updates["status"] = "Pending"
        if reason:
            self._pending_updates.setdefault("notes", "")
            self._pending_updates["notes"] += f" Follow-up reason: {reason}."
        logger.info("Follow-up scheduled for %s (lead=%s)", follow_date, self.lead_id)
        return ToolResult(
            True,
            "add_follow_up",
            f"Follow-up scheduled for {follow_date}",
            {"follow_up_date": follow_date, "reason": reason},
        )

    def _tool_mark_not_interested(self, params: dict) -> ToolResult:
        """Mark the prospect as not interested."""
        reason = params.get("reason", "No reason given")
        self._pending_updates["status"] = "Not Interested"
        self._pending_updates["qualification"] = "Unqualified"
        self._pending_updates["notes"] = f"Declined: {reason}"
        logger.info("Lead %s marked not interested: %s", self.lead_id, reason)
        return ToolResult(
            True,
            "mark_not_interested",
            f"Marked not interested: {reason}",
            {"reason": reason},
        )

    def _tool_save_requirement(self, params: dict) -> ToolResult:
        """Save a customer requirement."""
        req = params.get("requirement", "")
        if not req:
            return ToolResult(False, "save_requirement", "No requirement provided", {})

        self._requirements.append(req)
        self._pending_updates["customer_requirements"] = "; ".join(self._requirements)
        return ToolResult(
            True,
            "save_requirement",
            f"Requirement saved: {req}",
            {"requirement": req},
        )

    def _tool_save_objection(self, params: dict) -> ToolResult:
        """Record an objection."""
        objection = params.get("objection", "")
        if not objection:
            return ToolResult(False, "save_objection", "No objection provided", {})

        self._objections.append(objection)
        self._pending_updates["objections_raised"] = "; ".join(self._objections)
        return ToolResult(
            True,
            "save_objection",
            f"Objection recorded: {objection}",
            {"objection": objection},
        )

    def _tool_update_crm(self, params: dict) -> ToolResult:
        """Update a single CRM field."""
        field = params.get("field", "")
        value = params.get("value", "")
        valid = {
            "status",
            "qualification",
            "notes",
            "conversation_summary",
            "customer_requirements",
            "objections_raised",
            "follow_up_date",
            "meeting_datetime",
        }
        if field not in valid:
            return ToolResult(False, "update_crm", f"Invalid field: {field}", {})
        self._pending_updates[field] = value
        logger.info("CRM field queued: %s=%s (lead=%s)", field, value, self.lead_id)
        return ToolResult(True, "update_crm", f"Updated {field}", {field: value})

    def _tool_mark_qualification(self, params: dict) -> ToolResult:
        """Set lead qualification."""
        level = params.get("level", "")
        if not level:
            return ToolResult(False, "mark_qualification", "No level provided", {})
        self._pending_updates["qualification"] = level
        return ToolResult(
            True, "mark_qualification", f"Qualification set to {level}", {"level": level}
        )

    def _tool_save_notes(self, params: dict) -> ToolResult:
        """Append notes."""
        note = params.get("note", "")
        if not note:
            return ToolResult(False, "save_notes", "No note provided", {})
        existing = self._pending_updates.get("notes", "")
        self._pending_updates["notes"] = f"{existing} {note}".strip()
        return ToolResult(True, "save_notes", "Note saved", {"note": note})

    def _tool_send_email(self, params: dict) -> ToolResult:
        """Simulate sending an email -- logs only, never actually sends."""
        subject = params.get("subject", "")
        body = params.get("body", "")
        logger.info(
            "[EMAIL SIMULATION] lead=%s subject=%r body=%d chars",
            self.lead_id,
            subject,
            len(body),
        )
        return ToolResult(
            True,
            "send_email",
            f"Email simulated (not sent): {subject}",
            {"subject": subject, "simulated": True},
        )

    def flush_to_crm(self) -> None:
        """Write all pending updates to the Excel CRM in a single transaction."""
        if not self._pending_updates:
            logger.debug("No pending tool updates to flush for lead %s", self.lead_id)
            return

        import excel_crm

        try:
            excel_crm.update_lead(
                self.excel_path,
                self.lead_id,
                self._pending_updates,
                self.sheet_name,
            )
            logger.info(
                "Flushed %d tool updates to CRM for lead %s: %s",
                len(self._pending_updates),
                self.lead_id,
                list(self._pending_updates.keys()),
            )
            self._pending_updates.clear()
        except Exception as e:
            logger.error("Failed to flush tool updates to CRM: %s", e)
            raise

    def get_pending_updates(self) -> dict[str, Any]:
        """Return the current pending updates without flushing."""
        return dict(self._pending_updates)
