"""Tests for conversation.py with mocked LLM."""

import json
from unittest.mock import patch

import conversation as conv_mod
from conversation import Conversation, LLMUsage

SAMPLE_KB = "## Pricing\nStarter plan is $19/mo.\n\n## Features\nCRM and calling."


def _make_usage_reply(text: str) -> tuple[str, LLMUsage]:
    """Helper to create (reply, usage) tuples for mocking chat_with_usage."""
    return text, LLMUsage(prompt_tokens=50, completion_tokens=20, inference_ms=100.0)


@patch.object(
    conv_mod.llm_client,
    "chat_with_usage",
    return_value=_make_usage_reply("Hi, this is Alex from Acme. How are you?"),
)
def test_opening_line(mock_chat, sample_config):
    lead = {"lead_id": "L001", "name": "Jane"}
    convo = Conversation(
        lead=lead,
        company_name="Acme",
        caller_purpose="demo",
        knowledge_base=SAMPLE_KB,
        llm_config={**sample_config["llm"], "stream": False},
        max_turns=2,
        rag_config=sample_config["rag"],
    )
    reply = convo.agent_opening_line()
    assert reply == "Hi, this is Alex from Acme. How are you?"
    mock_chat.assert_called_once()


@patch.object(conv_mod.llm_client, "chat_with_usage")
def test_memory_preserves_team_size(mock_chat, sample_config):
    mock_chat.side_effect = [
        _make_usage_reply("Great, tell me about your team."),
        _make_usage_reply(
            '{"status":"Pending","qualification":"Warm","conversation_summary":"s",'
            '"customer_requirements":"","objections_raised":"","follow_up_date":"",'
            '"meeting_datetime":"","notes":""}'
        ),
    ]
    lead = {"lead_id": "L001", "name": "Jane"}
    convo = Conversation(
        lead=lead,
        company_name="Acme",
        caller_purpose="demo",
        knowledge_base=SAMPLE_KB,
        llm_config={**sample_config["llm"], "stream": False},
        max_turns=2,
        rag_config=sample_config["rag"],
    )
    convo.respond_to("We have 8 people on the sales team")
    assert convo.memory.team_size == "8"


@patch.object(
    conv_mod.llm_client,
    "chat_with_usage",
    return_value=_make_usage_reply("Thanks, have a great day!"),
)
def test_conversation_ends_on_phrase(mock_chat, sample_config):
    lead = {"lead_id": "L001", "name": "Jane"}
    convo = Conversation(
        lead=lead,
        company_name="Acme",
        caller_purpose="demo",
        knowledge_base=SAMPLE_KB,
        llm_config={**sample_config["llm"], "stream": False},
        max_turns=10,
        rag_config=sample_config["rag"],
    )
    convo.respond_to("Not interested, bye")
    assert convo.ended


@patch.object(conv_mod.llm_client, "chat_with_usage")
def test_total_usage_accumulated(mock_chat, sample_config):
    """LLMUsage accumulates across multiple turns."""
    mock_chat.side_effect = [
        _make_usage_reply("Hello!"),
        _make_usage_reply("Tell me more."),
        _make_usage_reply("Thanks, have a great day!"),
    ]
    lead = {"lead_id": "L001", "name": "Jane"}
    convo = Conversation(
        lead=lead,
        company_name="Acme",
        caller_purpose="demo",
        knowledge_base=SAMPLE_KB,
        llm_config={**sample_config["llm"], "stream": False},
        max_turns=10,
        rag_config=sample_config["rag"],
    )
    convo.agent_opening_line()
    convo.respond_to("Hi there")
    convo.respond_to("Not interested, bye")

    assert convo.total_usage.prompt_tokens >= 150
    assert convo.total_usage.completion_tokens >= 60
    assert convo.total_usage.inference_ms > 0


@patch.object(conv_mod.llm_client, "chat_with_usage")
@patch.object(conv_mod.llm_client, "chat")
def test_history_trim_and_summarise(mock_chat_simple, mock_chat_usage, sample_config):
    """Test that _trim_history_if_needed summarises older turns when max_history_turns is exceeded."""
    # We want max_history_turns = 1 (meaning keep 2 assistant/user messages + system prompt = 3 messages)
    sample_config["llm"]["max_history_turns"] = 1

    mock_chat_usage.return_value = _make_usage_reply("Some agent line")
    mock_chat_simple.return_value = "Summary of conversation: Jane wants pricing."

    lead = {"lead_id": "L001", "name": "Jane"}
    convo = Conversation(
        lead=lead,
        company_name="Acme",
        caller_purpose="demo",
        knowledge_base=SAMPLE_KB,
        llm_config=sample_config["llm"],
        max_turns=5,
        rag_config=sample_config["rag"],
    )

    # 1. Opening turn (adds assistant opening)
    convo.agent_opening_line()
    # 2. Turn 1 (adds user respond_to + assistant reply)
    convo.respond_to("I need pricing")
    # 3. Turn 2 (adds user respond_to + assistant reply) -> should trigger trim
    convo.respond_to("Are there integrations?")

    assert convo.conversation_summary == "Summary of conversation: Jane wants pricing."
    # The system prompt should contain the summary now
    assert "Summary of conversation: Jane wants pricing." in convo.messages[0]["content"]


@patch.object(conv_mod.llm_client, "chat_with_usage")
def test_tool_call_parsing(mock_chat_usage, sample_config):
    """Inject <tool_call> tags in LLM response and ensure they are parsed and executed."""
    # First LLM call schedules meeting, second LLM call gives the conversation reply
    mock_chat_usage.side_effect = [
        _make_usage_reply(
            '<tool_call>{"name": "schedule_meeting", "parameters": {"datetime": "2026-07-15 10:00"}}</tool_call>'
        ),
        _make_usage_reply("I have booked that for you!"),
        _make_usage_reply(
            '<tool_call>{"name": "add_follow_up", "parameters": {"date": "2026-07-16", "reason": "budget"}}</tool_call>'
        ),
        _make_usage_reply("I have set a follow up!"),
    ]

    lead = {"lead_id": "L001", "name": "Jane"}
    convo = Conversation(
        lead=lead,
        company_name="Acme",
        caller_purpose="demo",
        knowledge_base=SAMPLE_KB,
        llm_config=sample_config["llm"],
        max_turns=5,
        rag_config=sample_config["rag"],
        excel_path="dummy.xlsx",
    )

    reply1 = convo.respond_to("Let's schedule a demo.")
    assert convo.memory.meeting_datetime == "2026-07-15 10:00"

    reply2 = convo.respond_to("Also follow up tomorrow.")
    assert convo.memory.follow_up_date == "2026-07-16"


@patch.object(conv_mod.llm_client, "chat_with_usage")
def test_malformed_tool_call(mock_chat_usage, sample_config):
    """Verify malformed JSON inside tool_call tag is ignored gracefully."""
    mock_chat_usage.return_value = _make_usage_reply(
        '<tool_call>{"invalid": json}</tool_call> Hello'
    )
    lead = {"lead_id": "L001", "name": "Jane"}
    convo = Conversation(
        lead=lead,
        company_name="Acme",
        caller_purpose="demo",
        knowledge_base=SAMPLE_KB,
        llm_config=sample_config["llm"],
        max_turns=3,
        rag_config=sample_config["rag"],
        excel_path="dummy.xlsx",
    )
    reply = convo.respond_to("hello")
    assert reply == "Hello"


@patch.object(conv_mod.llm_client, "chat")
def test_extract_result_success(mock_chat_simple, sample_config):
    """extract_result successfully parses valid JSON extraction from LLM."""
    mock_chat_simple.return_value = json.dumps(
        {
            "status": "Booked",
            "qualification": "Hot",
            "conversation_summary": "Prospect booked a meeting.",
            "customer_requirements": "5 users",
            "objections_raised": "None",
            "follow_up_date": "",
            "meeting_datetime": "2026-07-15 10:00",
            "notes": "Keen to start",
        }
    )

    lead = {"lead_id": "L001", "name": "Jane"}
    convo = Conversation(
        lead=lead,
        company_name="Acme",
        caller_purpose="demo",
        knowledge_base=SAMPLE_KB,
        llm_config=sample_config["llm"],
        max_turns=3,
        rag_config=sample_config["rag"],
    )

    convo.full_transcript.append({"role": "user", "content": "Hi"})
    convo.full_transcript.append({"role": "assistant", "content": "Hello"})

    result = convo.extract_result()
    assert result.status == "Booked"
    assert result.qualification == "Hot"
    assert result.meeting_datetime == "2026-07-15 10:00"

    # Check as_update_dict
    ud = result.as_update_dict()
    assert ud["status"] == "Booked"
    assert ud["qualification"] == "Hot"


@patch.object(conv_mod.llm_client, "chat")
def test_extract_result_fallback(mock_chat_simple, sample_config):
    """extract_result uses safe fallback data when LLM extraction returns malformed output."""
    mock_chat_simple.return_value = "This is not valid JSON at all!"

    lead = {"lead_id": "L001", "name": "Jane"}
    convo = Conversation(
        lead=lead,
        company_name="Acme",
        caller_purpose="demo",
        knowledge_base=SAMPLE_KB,
        llm_config=sample_config["llm"],
        max_turns=3,
        rag_config=sample_config["rag"],
    )

    result = convo.extract_result()
    assert result.status == "Pending"
    assert result.qualification == "Not Yet Assessed"
    assert "Could not parse" in result.conversation_summary


@patch.object(conv_mod.llm_client, "chat")
def test_summarise_messages_failure(mock_chat, sample_config):
    """Verify summarise messages returns fallback string if LLM call fails."""
    mock_chat.side_effect = Exception("LLM crash")
    lead = {"lead_id": "L001", "name": "Jane"}
    convo = Conversation(
        lead=lead,
        company_name="Acme",
        caller_purpose="demo",
        knowledge_base=SAMPLE_KB,
        llm_config=sample_config["llm"],
        max_turns=3,
        rag_config=sample_config["rag"],
    )
    res = convo._summarise_messages([{"role": "user", "content": "Hello"}])
    assert "Hello" in res  # fallback returns plain transcript


@patch.object(conv_mod.llm_client, "chat")
def test_extract_result_merge_memory_and_tools(mock_chat, sample_config):
    """Verify memory values and tool pending updates are correctly merged into extraction result."""
    # LLM returns Pending/empty fields
    mock_chat.return_value = json.dumps(
        {
            "status": "Pending",
            "qualification": "Warm",
            "conversation_summary": "Prospect called.",
            "customer_requirements": "",
            "objections_raised": "",
            "follow_up_date": "",
            "meeting_datetime": "",
            "notes": "",
        }
    )

    lead = {"lead_id": "L001", "name": "Jane"}
    convo = Conversation(
        lead=lead,
        company_name="Acme",
        caller_purpose="demo",
        knowledge_base=SAMPLE_KB,
        llm_config=sample_config["llm"],
        max_turns=3,
        rag_config=sample_config["rag"],
        excel_path="dummy.xlsx",
    )

    # Set memory values
    convo.memory.set_meeting("2026-07-15 10:00")
    convo.memory.set_follow_up("2026-07-16")
    convo.memory.requirements.append("pricing details")
    convo.memory.objections.append("too expensive")

    # Set tool pending updates
    convo.tool_executor.execute("save_notes", {"note": "special note"})

    result = convo.extract_result()
    assert result.status == "Booked"  # Pending upgraded to Booked because meeting set
    assert result.meeting_datetime == "2026-07-15 10:00"
    assert result.follow_up_date == "2026-07-16"
    assert result.customer_requirements == "pricing details"
    assert result.objections_raised == "too expensive"
    assert result.notes == "special note"
