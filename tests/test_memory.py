"""Tests for memory.py."""

from memory import CustomerMemory


def test_absorb_team_size():
    mem = CustomerMemory()
    mem.absorb_turn("user", "We have 6 people on the sales team")
    assert mem.team_size == "6"


def test_meeting_never_lost():
    mem = CustomerMemory()
    mem.set_meeting("2026-07-14 15:00")
    mem.absorb_turn("user", "Actually never mind")
    assert mem.meeting_datetime == "2026-07-14 15:00"


def test_prompt_section_includes_facts():
    mem = CustomerMemory()
    mem.requirements.append("pricing info")
    mem.set_meeting("2026-07-14 15:00")
    section = mem.to_prompt_section()
    assert "Booked meeting" in section
    assert "pricing info" in section


def test_absorb_empty_turn():
    mem = CustomerMemory()
    mem.absorb_turn("user", "   ")
    assert not mem.requirements
    assert not mem.objections


def test_current_tools_spreadsheets():
    mem = CustomerMemory()
    mem.absorb_turn("user", "We manage our leads via spreadsheets.")
    assert mem.current_tools == "spreadsheets"
    # Absorb another turn, should not change
    mem.absorb_turn("user", "Excel is fine too")
    assert mem.current_tools == "spreadsheets"


def test_objection_extraction():
    mem = CustomerMemory()
    mem.absorb_turn("user", "I'm worried this is too expensive.")
    assert len(mem.objections) == 1
    assert "too expensive" in mem.objections[0]


def test_assistant_meeting_commitments():
    # Test meeting pattern 1: "on Wednesday at 2pm"
    mem1 = CustomerMemory()
    mem1.absorb_turn("assistant", "I can book a meeting on Wednesday at 2pm.")
    assert mem1.meeting_datetime == "Wednesday 2pm"

    # Test meeting pattern 2: ISO datetime
    mem2 = CustomerMemory()
    mem2.absorb_turn("assistant", "Scheduled for 2026-07-14 15:30.")
    assert mem2.meeting_datetime == "2026-07-14 15:30"

    # Test meeting pattern 3: "Friday morning at 10am"
    mem3 = CustomerMemory()
    mem3.absorb_turn("assistant", "How about Friday morning at 10am?")
    assert mem3.meeting_datetime == "Friday 10am"


def test_set_follow_up():
    mem = CustomerMemory()
    mem.set_follow_up("")
    assert mem.follow_up_date == ""
    mem.set_follow_up("2026-07-15")
    assert mem.follow_up_date == "2026-07-15"


def test_to_prompt_section_all_fields():
    mem = CustomerMemory()
    mem.meeting_datetime = "2026-07-14 15:00"
    mem.follow_up_date = "2026-07-15"
    mem.team_size = "10"
    mem.current_tools = "spreadsheets"
    mem.requirements = ["pricing", "calling"]
    mem.objections = ["too expensive"]
    mem.notes = ["needs integrations details"]

    section = mem.to_prompt_section()
    assert "Booked meeting: 2026-07-14 15:00" in section
    assert "Follow-up date: 2026-07-15" in section
    assert "Team size: 10 people" in section
    assert "Current tools: spreadsheets" in section
    assert "Customer needs: pricing; calling" in section
    assert "Objections raised: too expensive" in section
    assert "Notes: needs integrations details" in section

    assert mem.char_count() == len(section)


def test_to_prompt_section_empty():
    mem = CustomerMemory()
    assert mem.to_prompt_section() == ""
    assert mem.char_count() == 0


def test_absorb_pricing_and_scheduling():
    mem = CustomerMemory()
    mem.absorb_turn("user", "Tell me about pricing, and let's book a demo.")
    assert "pricing information" in mem.requirements
    assert "demo/meeting scheduling" in mem.requirements
