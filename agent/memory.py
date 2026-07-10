"""
memory.py -- intelligent conversation memory for the AI Voice Sales Agent.

Preserves important customer facts and meeting details across history
trimming and summarisation so context is reduced without information loss.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from logger_setup import get_logger

logger = get_logger(__name__)

# Patterns for extracting durable facts from conversation text
_MEETING_PATTERNS = [
    re.compile(
        r"(?:meeting|demo|call|walkthrough)\s+(?:on\s+)?(\w+day)\s+(?:at\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
        re.I,
    ),
    re.compile(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", re.I),
    re.compile(
        r"(\w+day)\s+(?:afternoon|morning|evening)?\s*(?:at\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
        re.I,
    ),
]
_TEAM_SIZE_PATTERN = re.compile(
    r"(\d+)\s*(?:people|person|reps?|users?|on the (?:sales )?team)", re.I
)
_PRICING_KEYWORDS = {"price", "pricing", "cost", "budget", "subscription", "plan"}
_OBJECTION_KEYWORDS = {"concern", "worried", "expensive", "not sure", "hesitant", "contract"}


@dataclass
class CustomerMemory:
    """Persistent facts that survive history trimming and summarisation."""

    requirements: list[str] = field(default_factory=list)
    objections: list[str] = field(default_factory=list)
    meeting_datetime: str = ""
    follow_up_date: str = ""
    team_size: str = ""
    current_tools: str = ""
    notes: list[str] = field(default_factory=list)

    def absorb_turn(self, role: str, text: str) -> None:
        """Extract durable facts from a single conversation turn."""
        if not text.strip():
            return

        low = text.lower()

        if role == "user":
            self._extract_user_facts(text, low)
        elif role == "assistant":
            self._extract_agent_commitments(text, low)

    def _extract_user_facts(self, text: str, low: str) -> None:
        """Pull requirements, objections, and context from prospect speech."""
        if any(kw in low for kw in ("spreadsheet", "excel", "manual")):
            if not self.current_tools:
                self.current_tools = "spreadsheets"
                logger.debug("Memory fact added [current_tools]: spreadsheets")
        if any(kw in low for kw in _PRICING_KEYWORDS):
            self._add_unique("requirements", "pricing information")
        if any(kw in low for kw in _OBJECTION_KEYWORDS):
            self._add_unique("objections", text.strip()[:120])

        team_match = _TEAM_SIZE_PATTERN.search(text)
        if team_match:
            self.team_size = team_match.group(1)

        if "book" in low or "schedule" in low or "demo" in low:
            self._add_unique("requirements", "demo/meeting scheduling")

    def _extract_agent_commitments(self, text: str, low: str) -> None:
        """Capture meeting times the agent commits to."""
        for pattern in _MEETING_PATTERNS:
            match = pattern.search(text)
            if match:
                meeting = " ".join(g for g in match.groups() if g).strip()
                if meeting and not self.meeting_datetime:
                    self.meeting_datetime = meeting
                    logger.info("Memory captured meeting detail: %s", meeting)
                break

    def _add_unique(self, field_name: str, value: str) -> None:
        """Append a value to a list field if not already present."""
        items: list[str] = getattr(self, field_name)
        if value not in items:
            items.append(value)
            logger.debug("Memory fact added [%s]: %s", field_name, value[:80])

    def set_meeting(self, datetime_str: str) -> None:
        """Explicitly record a booked meeting -- never overwritten by trimming."""
        if datetime_str:
            self.meeting_datetime = datetime_str
            logger.info("Memory locked meeting: %s", datetime_str)

    def set_follow_up(self, date_str: str) -> None:
        """Record a follow-up date."""
        if date_str:
            self.follow_up_date = date_str

    def to_prompt_section(self) -> str:
        """Render persistent facts for injection into the system prompt."""
        lines: list[str] = []
        if self.meeting_datetime:
            lines.append(f"- Booked meeting: {self.meeting_datetime}")
        if self.follow_up_date:
            lines.append(f"- Follow-up date: {self.follow_up_date}")
        if self.team_size:
            lines.append(f"- Team size: {self.team_size} people")
        if self.current_tools:
            lines.append(f"- Current tools: {self.current_tools}")
        if self.requirements:
            lines.append(f"- Customer needs: {'; '.join(self.requirements)}")
        if self.objections:
            lines.append(f"- Objections raised: {'; '.join(self.objections)}")
        if self.notes:
            lines.append(f"- Notes: {'; '.join(self.notes)}")

        if not lines:
            return ""
        return "## Important customer facts (do not forget)\n" + "\n".join(lines)

    def char_count(self) -> int:
        """Return approximate character count of the memory section."""
        return len(self.to_prompt_section())
