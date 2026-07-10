"""Tests for tools.py."""

from unittest.mock import patch

import pytest
from tools import ToolExecutor


def test_schedule_meeting():
    ex = ToolExecutor("dummy.xlsx", "L001")
    result = ex.execute("schedule_meeting", {"datetime": "2026-07-14 15:00"})
    assert result.success
    assert ex.get_pending_updates()["meeting_datetime"] == "2026-07-14 15:00"
    assert ex.get_pending_updates()["status"] == "Booked"
    assert ex.get_pending_updates()["qualification"] == "Hot"

    # Test scheduling meeting without datetime
    result_fail = ex.execute("schedule_meeting", {})
    assert not result_fail.success


def test_add_follow_up():
    ex = ToolExecutor("dummy.xlsx", "L001")
    result = ex.execute("add_follow_up", {"date": "2026-07-15", "reason": "Ask about budget"})
    assert result.success
    assert ex.get_pending_updates()["follow_up_date"] == "2026-07-15"
    assert ex.get_pending_updates()["status"] == "Pending"
    assert "Ask about budget" in ex.get_pending_updates()["notes"]

    # Test without date
    result_fail = ex.execute("add_follow_up", {})
    assert not result_fail.success


def test_mark_not_interested():
    ex = ToolExecutor("dummy.xlsx", "L001")
    result = ex.execute("mark_not_interested", {"reason": "Too expensive"})
    assert result.success
    assert ex.get_pending_updates()["status"] == "Not Interested"
    assert ex.get_pending_updates()["qualification"] == "Unqualified"
    assert "Too expensive" in ex.get_pending_updates()["notes"]


def test_save_requirement():
    ex = ToolExecutor("dummy.xlsx", "L001")
    result = ex.execute("save_requirement", {"requirement": "Need integrations"})
    assert result.success
    assert ex.get_pending_updates()["customer_requirements"] == "Need integrations"

    # Save a second one
    result2 = ex.execute("save_requirement", {"requirement": "Under $20/mo"})
    assert result2.success
    assert ex.get_pending_updates()["customer_requirements"] == "Need integrations; Under $20/mo"

    # Test without requirement
    result_fail = ex.execute("save_requirement", {})
    assert not result_fail.success


def test_save_objection():
    ex = ToolExecutor("dummy.xlsx", "L001")
    result = ex.execute("save_objection", {"objection": "No budget"})
    assert result.success
    assert ex.get_pending_updates()["objections_raised"] == "No budget"

    # Save a second objection
    result2 = ex.execute("save_objection", {"objection": "Too complex"})
    assert result2.success
    assert ex.get_pending_updates()["objections_raised"] == "No budget; Too complex"

    # Test without objection
    result_fail = ex.execute("save_objection", {})
    assert not result_fail.success


def test_update_crm():
    ex = ToolExecutor("dummy.xlsx", "L001")
    result = ex.execute("update_crm", {"field": "status", "value": "Called"})
    assert result.success
    assert ex.get_pending_updates()["status"] == "Called"

    # Test invalid field
    result_fail = ex.execute("update_crm", {"field": "invalid_field", "value": "val"})
    assert not result_fail.success


def test_mark_qualification():
    ex = ToolExecutor("dummy.xlsx", "L001")
    result = ex.execute("mark_qualification", {"level": "Warm"})
    assert result.success
    assert ex.get_pending_updates()["qualification"] == "Warm"

    # Test without level
    result_fail = ex.execute("mark_qualification", {})
    assert not result_fail.success


def test_save_notes():
    ex = ToolExecutor("dummy.xlsx", "L001")
    result = ex.execute("save_notes", {"note": "Spoke to lead dev"})
    assert result.success
    assert ex.get_pending_updates()["notes"] == "Spoke to lead dev"

    # Save notes again
    result2 = ex.execute("save_notes", {"note": "Interested in Starter plan"})
    assert result2.success
    assert ex.get_pending_updates()["notes"] == "Spoke to lead dev Interested in Starter plan"

    # Test without note
    result_fail = ex.execute("save_notes", {})
    assert not result_fail.success


def test_send_email_simulation():
    ex = ToolExecutor("dummy.xlsx", "L001")
    result = ex.execute("send_email", {"subject": "Hi", "body": "Follow up"})
    assert result.success
    assert result.data.get("simulated") is True


def test_unknown_tool():
    ex = ToolExecutor("dummy.xlsx", "L001")
    result = ex.execute("nonexistent_tool", {})
    assert not result.success


def test_flush_to_crm(temp_excel):
    """Verify flush_to_crm calls excel_crm.update_lead and clears pending updates."""
    ex = ToolExecutor(temp_excel, "L001")
    ex.execute("schedule_meeting", {"datetime": "2026-07-14 15:00"})
    assert ex.get_pending_updates()

    # Flush
    ex.flush_to_crm()
    assert not ex.get_pending_updates()

    # Verify updates exist in temp CRM
    import excel_crm

    lead = excel_crm.get_lead_by_id(temp_excel, "L001")
    assert lead["status"] == "Booked"
    assert lead["meeting_datetime"] == "2026-07-14 15:00"


def test_flush_to_crm_no_pending():
    """Flushing with no pending updates should do nothing and not raise."""
    ex = ToolExecutor("dummy.xlsx", "L001")
    # This should return immediately without trying to open or modify a file
    ex.flush_to_crm()


def test_execute_handler_exception():
    """Verify exceptions in handlers are caught and returned as ToolResult success=False."""
    ex = ToolExecutor("dummy.xlsx", "L001")
    # Passing None instead of a dict will raise AttributeError: 'NoneType' object has no attribute 'get'
    result = ex.execute("schedule_meeting", None)
    assert result.success is False
    assert "Tool execution failed" in result.message


def test_flush_to_crm_exception():
    """Verify exceptions during flush are logged and re-raised."""
    ex = ToolExecutor("dummy.xlsx", "L001")
    ex.execute("schedule_meeting", {"datetime": "2026-07-14 15:00"})

    with patch("excel_crm.update_lead", side_effect=Exception("Disk full")):
        with pytest.raises(Exception, match="Disk full"):
            ex.flush_to_crm()
