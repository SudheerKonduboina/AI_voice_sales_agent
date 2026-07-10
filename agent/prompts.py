"""
prompts.py -- builds the system prompt for the live conversation and the
extraction prompt used to turn a finished call transcript into the
structured JSON that excel_crm.update_lead() expects.
"""

from __future__ import annotations

PROMPT_VERSION: str = "1.0"

SYSTEM_PROMPT_TEMPLATE = """# Prompt-Version: {prompt_version}
You are a professional outbound sales representative calling on behalf of {company_name}.
You are calling {lead_name} about {caller_purpose}.

Rules:
- Maximum 50 words per response.
- Ask only one question at a time.
- Never invent facts. Answer using ONLY the knowledge base.
- Don't repeat yourself.
- Be friendly and conversational.
- If they're not interested, respect that and end gracefully.
- If you don't know something, say you'll follow up.

## Available Actions (Tool Calls)
If you need to perform an action, output a JSON tool call wrapped in <tool_call>...</tool_call> tags.
Do NOT fabricate successful actions in your conversational text; wait for the tool execution result.
Format:
<tool_call>{{"name": "tool_name", "parameters": {{"param_key": "value"}}}}</tool_call>

Available Tools:
- schedule_meeting: Book meeting. Param: "datetime" (YYYY-MM-DD HH:MM)
- add_follow_up: Follow up call. Params: "date" (YYYY-MM-DD), "reason" (string)
- mark_not_interested: Record rejection. Param: "reason" (string)
- save_requirement: Save customer requirement. Param: "requirement" (string)
- save_objection: Save customer objection. Param: "objection" (string)
- update_crm: Update CRM field. Params: "field", "value"
- mark_qualification: Set qualification. Param: "level" (Hot/Warm/Cold/Unqualified)
- save_notes: Append notes. Param: "note" (string)
- send_email: Simulate email send. Params: "subject", "body"
{summary_section}
## Knowledge base
{knowledge_base}

Begin the call now with a brief, friendly introduction.
"""

SUMMARY_SECTION_TEMPLATE = """
## Conversation so far
{summary}
"""

FACTS_SECTION_TEMPLATE = """
{facts}
"""

# The JSON the LLM must produce once the call has ended, so the runner can
# write it straight into the Excel CRM via excel_crm.update_lead().
CALL_RESULT_SCHEMA = {
    "status": "one of: Booked, Not Interested, No Answer, Pending",
    "qualification": "one of: Hot, Warm, Cold, Unqualified, Not Yet Assessed",
    "conversation_summary": "2-3 sentence plain-English summary of the call",
    "customer_requirements": "what the prospect said they need, or 'N/A'",
    "objections_raised": "objections raised, or 'None'",
    "follow_up_date": "YYYY-MM-DD if they asked to be recontacted later, else ''",
    "meeting_datetime": "YYYY-MM-DD HH:MM if a meeting was booked, else ''",
    "notes": "anything else useful for a human rep picking this up",
}

EXTRACTION_PROMPT_TEMPLATE = """Below is a transcript of a completed sales call. Extract the outcome as a
single JSON object with EXACTLY these keys and nothing else -- no markdown
fences, no preamble, no commentary:

{schema}

Rules:
- status MUST be one of: Booked, Not Interested, No Answer, Pending
- qualification MUST be one of: Hot, Warm, Cold, Unqualified, Not Yet Assessed
- If the call never connected / no one spoke, status = "No Answer" and
  qualification = "Not Yet Assessed", other fields = "".
- Dates must be in YYYY-MM-DD format, datetimes in YYYY-MM-DD HH:MM.
- Output raw JSON only.

TRANSCRIPT:
{transcript}
"""

SUMMARY_PROMPT_TEMPLATE = """Summarise the following sales call excerpt in 3-5 bullet points.
Focus on: what the prospect said, their needs, objections, and any decisions made.
Be factual. Do not invent information. Maximum 80 words.

CONVERSATION:
{transcript}
"""


def build_system_prompt(
    company_name: str,
    caller_purpose: str,
    lead_name: str,
    knowledge_base: str,
    conversation_summary: str = "",
    customer_facts: str = "",
) -> str:
    """Build the system prompt, optionally injecting summary and persistent facts."""
    summary_section = ""
    if conversation_summary:
        summary_section = SUMMARY_SECTION_TEMPLATE.format(summary=conversation_summary)

    facts_section = ""
    if customer_facts:
        facts_section = FACTS_SECTION_TEMPLATE.format(facts=customer_facts)

    return SYSTEM_PROMPT_TEMPLATE.format(
        prompt_version=PROMPT_VERSION,
        company_name=company_name,
        caller_purpose=caller_purpose,
        lead_name=lead_name,
        knowledge_base=knowledge_base,
        summary_section=summary_section + facts_section,
    )


def build_extraction_prompt(transcript: str) -> str:
    """Build the prompt that asks the LLM to extract structured CRM data."""
    import json

    return EXTRACTION_PROMPT_TEMPLATE.format(
        schema=json.dumps(CALL_RESULT_SCHEMA, indent=2),
        transcript=transcript,
    )


def build_summary_prompt(transcript: str) -> str:
    """Build the prompt that asks the LLM to summarise old conversation turns."""
    return SUMMARY_PROMPT_TEMPLATE.format(transcript=transcript)


def get_prompt_version() -> str:
    """Return the current prompt version string."""
    return PROMPT_VERSION
