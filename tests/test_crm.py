"""Tests for excel_crm.py."""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import excel_crm
import pytest
from excel_crm import CRMError, LeadUpdate, _acquire_lock, _release_lock


def test_lead_update_validation():
    update = LeadUpdate(status="Booked", qualification="Hot")
    update.validate()

    with pytest.raises(ValueError, match="status"):
        LeadUpdate(status="Invalid").validate()

    with pytest.raises(ValueError, match="qualification"):
        LeadUpdate(qualification="Invalid").validate()


def test_sanitize_invalid_status_and_dates():
    sanitized = excel_crm._sanitize_updates(
        {
            "status": "INVALID",
            "qualification": "BAD",
            "follow_up_date": "bad-date",
            "meeting_datetime": "bad-datetime",
        }
    )
    assert sanitized["status"] == "Pending"
    assert sanitized["qualification"] == "Not Yet Assessed"
    assert sanitized["follow_up_date"] == ""
    assert sanitized["meeting_datetime"] == ""


def test_find_row_errors(temp_excel):
    # Test KeyError when lead is not found
    with pytest.raises(KeyError, match="not found"):
        excel_crm.update_lead(temp_excel, "L_NONEXISTENT", {"notes": "test"})


def test_find_row_duplicates(temp_excel):
    # Simulate duplicate lead ID by mocking ws cell values
    wb = excel_crm.load_workbook(temp_excel)
    ws = wb["Leads"]
    # Write duplicate L001 into row 3
    headers = excel_crm._header_map(ws)
    ws.cell(row=3, column=headers["Lead ID"], value="L001")

    with patch("excel_crm.load_workbook", return_value=wb):
        with pytest.raises(ValueError, match="Duplicate Lead ID"):
            excel_crm.update_lead(temp_excel, "L001", {"notes": "test"})


def test_date_validation_follow_up():
    """Invalid follow_up_date format raises ValueError."""
    with pytest.raises(ValueError, match="follow_up_date"):
        LeadUpdate(follow_up_date="July 14th").validate()


def test_date_validation_meeting():
    """Invalid meeting_datetime format raises ValueError."""
    with pytest.raises(ValueError, match="meeting_datetime"):
        LeadUpdate(meeting_datetime="next Tuesday 3pm").validate()


def test_valid_dates():
    """Valid date formats should not raise."""
    update = LeadUpdate(
        follow_up_date="2026-07-14",
        meeting_datetime="2026-07-14 15:30",
    )
    update.validate()  # should not raise


def test_mark_opted_out(temp_excel):
    """mark_opted_out should set status to 'Opted Out'."""
    excel_crm.mark_opted_out(temp_excel, "L001")
    leads = excel_crm.get_all_leads(temp_excel)
    l001 = next(ld for ld in leads if ld["lead_id"] == "L001")
    assert l001["status"] == "Opted Out"


def test_mark_no_answer(temp_excel):
    """mark_no_answer should set status to 'No Answer'."""
    excel_crm.mark_no_answer(temp_excel, "L001")
    leads = excel_crm.get_all_leads(temp_excel)
    l001 = next(ld for ld in leads if ld["lead_id"] == "L001")
    assert l001["status"] == "No Answer"


def test_get_meetings_scheduled(temp_excel):
    """get_meetings_scheduled should return leads with meetings booked."""
    # Book a meeting for L001
    excel_crm.update_lead(
        temp_excel,
        "L001",
        {
            "status": "Booked",
            "meeting_datetime": "2026-07-14 15:30",
        },
    )
    meetings = excel_crm.get_meetings_scheduled(temp_excel)
    assert len(meetings) >= 1
    assert any(m["lead_id"] == "L001" for m in meetings)


def test_get_lead_by_id(temp_excel):
    """get_lead_by_id should return the correct lead or None."""
    lead = excel_crm.get_lead_by_id(temp_excel, "L001")
    assert lead is not None
    assert lead["lead_id"] == "L001"

    missing = excel_crm.get_lead_by_id(temp_excel, "LXXX")
    assert missing is None


def test_crm_error_is_runtime_error():
    """CRMError should be a subclass of RuntimeError."""
    assert issubclass(CRMError, RuntimeError)
    err = CRMError("test error")
    assert str(err) == "test error"


def test_update_lead_once_with_object(temp_excel):
    """Verify update_lead accepts LeadUpdate object directly."""
    update = LeadUpdate(notes="Direct object update")
    excel_crm.update_lead(temp_excel, "L001", update)
    lead = excel_crm.get_lead_by_id(temp_excel, "L001")
    assert lead["notes"] == "Direct object update"


def test_save_workbook_safely_failure(temp_excel):
    """Verify exception in save workbook triggers rollback and CRMError."""
    wb = excel_crm.load_workbook(temp_excel)
    # Mock save to raise OSError
    wb.save = MagicMock(side_effect=OSError("Disk write error"))

    with pytest.raises(CRMError, match="CRM transactional save failed"):
        excel_crm._save_workbook_safely(wb, temp_excel)


def test_get_pending_leads(temp_excel):
    """Verify get_pending_leads returns only Pending leads."""
    pending = excel_crm.get_pending_leads(temp_excel)
    assert len(pending) > 0
    # Make sure all returned leads have pending status
    for p in pending:
        assert p.get("status") in (None, "", "Pending")


def test_update_lead_validation_retry_loop(temp_excel):
    """Verify update_lead retries with sanitized updates on ValueError."""
    # We pass status="INVALID" which raises ValueError, and the retry loop should sanitize it to "Pending"
    excel_crm.update_lead(temp_excel, "L001", {"status": "INVALID"})
    lead = excel_crm.get_lead_by_id(temp_excel, "L001")
    assert lead["status"] == "Pending"


def test_update_lead_object_raises_immediately_on_validation_failure(temp_excel):
    """Verify that passing an invalid LeadUpdate object raises ValueError directly without retry/sanitization."""
    # We construct a LeadUpdate that raises ValueError inside validate()
    invalid_update = LeadUpdate(status="INVALID")
    with pytest.raises(ValueError, match="Invalid status"):
        excel_crm.update_lead(temp_excel, "L001", invalid_update)


# ---------------------------------------------------------------------------
# Locking, Concurrency, and Recovery verification tests
# ---------------------------------------------------------------------------
def test_crm_lock_timeout(temp_excel):
    """Verify lock acquisition times out if file is locked."""
    lock_path = temp_excel + ".lock"
    # Manually create the lock file
    with open(lock_path, "w") as f:
        f.write("locked")

    try:
        with pytest.raises(CRMError, match="Could not acquire lock"):
            _acquire_lock(temp_excel, timeout=0.2, delay=0.05)
    finally:
        _release_lock(lock_path)


def test_crm_lock_stale_recovery(temp_excel):
    """Verify lock acquisition recovers if lock file is stale (>15s)."""
    lock_path = temp_excel + ".lock"
    with open(lock_path, "w") as f:
        f.write("stale lock")

    # Backdate the modification time of the lock file to be 20 seconds ago
    past_time = time.time() - 20.0
    os.utime(lock_path, (past_time, past_time))

    # This should acquire lock successfully by deleting the stale lock
    lock = _acquire_lock(temp_excel, timeout=1.0, delay=0.05)
    assert os.path.exists(lock)
    _release_lock(lock)


def test_crm_lock_stale_recovery_exception(temp_excel):
    """Verify exception in stale lock age check is caught gracefully (covers lines 60-61)."""
    lock_path = temp_excel + ".lock"
    with open(lock_path, "w") as f:
        f.write("stale lock")

    # Mock os.path.getmtime to raise OSError
    with patch("os.path.getmtime", side_effect=OSError("File removed")):
        with pytest.raises(CRMError):
            _acquire_lock(temp_excel, timeout=0.2, delay=0.05)

    _release_lock(lock_path)


def test_crm_lock_release_fails_gracefully():
    """Verify lock release handles exceptions gracefully (e.g. file already deleted)."""
    # Should not raise if file doesn't exist
    _release_lock("nonexistent_lock_path.lock")


def test_crm_lock_release_exception():
    """Verify lock release exception logging when os.remove fails (covers lines 70-71)."""
    with patch("os.path.exists", return_value=True):
        with patch("os.remove", side_effect=OSError("Permission denied")):
            with patch("excel_crm.logger.warning") as mock_warn:
                _release_lock("dummy_lock.lock")
                assert mock_warn.called


def test_crm_concurrent_writes(temp_excel):
    """Verify concurrent leads updates do not raise exceptions and execute sequentially."""

    def perform_update(idx):
        excel_crm.update_lead(temp_excel, "L001", {"notes": f"Note {idx}"})

    # Start 4 concurrent update threads
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(perform_update, i) for i in range(4)]
        # All should complete successfully without raising exceptions
        for fut in futures:
            fut.result()

    lead = excel_crm.get_lead_by_id(temp_excel, "L001")
    # At least one note was written successfully
    assert "Note" in lead["notes"]
