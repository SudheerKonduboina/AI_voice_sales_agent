"""Tests for analytics.py."""

from pathlib import Path

import pytest
from analytics import AnalyticsStore, CallMetrics, get_analytics


def test_record_and_report(temp_analytics_dir):
    store = AnalyticsStore(report_dir=temp_analytics_dir)
    store.record_call(
        CallMetrics(
            lead_id="L001",
            lead_name="Test",
            status="Booked",
            qualification="Hot",
            duration_seconds=120.0,
            meeting_booked=True,
        )
    )
    report = store.generate_report()
    assert report["total_calls"] == 1
    assert report["booked_meetings"] == 1


def test_qualifications_breakdown(temp_analytics_dir):
    store = AnalyticsStore(report_dir=temp_analytics_dir)
    store.record_call(
        CallMetrics(
            lead_id="L1",
            lead_name="A",
            status="Booked",
            qualification="Hot",
            duration_seconds=60,
            meeting_booked=True,
        )
    )
    store.record_call(
        CallMetrics(
            lead_id="L2",
            lead_name="B",
            status="Called",
            qualification="Warm",
            duration_seconds=90,
        )
    )
    report = store.generate_report()
    assert report["qualifications"]["Hot"] == 1
    assert report["qualifications"]["Warm"] == 1


def test_success_rate_pct(temp_analytics_dir):
    """success_rate_pct should be (Booked + Called) / total * 100."""
    store = AnalyticsStore(report_dir=temp_analytics_dir)
    for status, qual in [
        ("Booked", "Hot"),
        ("Called", "Warm"),
        ("Not Interested", "Cold"),
        ("Pending", "Cold"),
    ]:
        store.record_call(
            CallMetrics(
                lead_id=f"L-{status}",
                lead_name="Test",
                status=status,
                qualification=qual,
                duration_seconds=60.0,
            )
        )
    report = store.generate_report()
    assert report["success_rate_pct"] == 50.0  # 2 out of 4
    assert report["total_calls"] == 4


def test_qualification_rate_pct(temp_analytics_dir):
    """qualification_rate_pct should be (Hot + Warm) / total * 100."""
    store = AnalyticsStore(report_dir=temp_analytics_dir)
    for qual in ["Hot", "Warm", "Cold"]:
        store.record_call(
            CallMetrics(
                lead_id=f"L-{qual}",
                lead_name="Test",
                status="Called",
                qualification=qual,
                duration_seconds=60.0,
            )
        )
    report = store.generate_report()
    assert report["qualification_rate_pct"] == pytest.approx(66.7, abs=0.1)


def test_per_status_breakdown(temp_analytics_dir):
    """per_status_breakdown should count each status."""
    store = AnalyticsStore(report_dir=temp_analytics_dir)
    for status in ["Booked", "Booked", "Not Interested"]:
        store.record_call(
            CallMetrics(
                lead_id=f"L-{status}",
                lead_name="Test",
                status=status,
                qualification="Warm",
                duration_seconds=60.0,
            )
        )
    report = store.generate_report()
    assert report["per_status_breakdown"]["Booked"] == 2
    assert report["per_status_breakdown"]["Not Interested"] == 1


def test_average_response_time_ms(temp_analytics_dir):
    """average_response_time_ms should be derived from inference_time_seconds."""
    store = AnalyticsStore(report_dir=temp_analytics_dir)
    store.record_call(
        CallMetrics(
            lead_id="L1",
            lead_name="Test",
            status="Called",
            qualification="Warm",
            duration_seconds=60.0,
            inference_time_seconds=0.5,
        )
    )
    store.record_call(
        CallMetrics(
            lead_id="L2",
            lead_name="Test",
            status="Called",
            qualification="Warm",
            duration_seconds=60.0,
            inference_time_seconds=1.5,
        )
    )
    report = store.generate_report()
    assert report["average_response_time_ms"] == 1000.0  # (500 + 1500) / 2


def test_persistence_round_trip(temp_analytics_dir):
    """Data should survive save/reload cycle."""
    store1 = AnalyticsStore(report_dir=temp_analytics_dir)
    store1.record_call(
        CallMetrics(
            lead_id="L1",
            lead_name="Alice",
            status="Booked",
            qualification="Hot",
            duration_seconds=120.0,
            prompt_tokens=100,
            completion_tokens=50,
        )
    )

    # Reload from the same directory
    store2 = AnalyticsStore(report_dir=temp_analytics_dir)
    assert len(store2.calls) == 1
    assert store2.calls[0].lead_id == "L1"
    assert store2.calls[0].prompt_tokens == 100

    report = store2.generate_report()
    assert report["total_prompt_tokens"] == 100
    assert report["total_completion_tokens"] == 50


def test_generate_report_empty(temp_analytics_dir):
    """Verify report generated on empty store is correct."""
    store = AnalyticsStore(report_dir=temp_analytics_dir)
    # Clear any loaded calls
    store.calls = []
    report = store.generate_report()
    assert report["total_calls"] == 0
    assert "generated_at" in report


def test_load_malformed_json_fallback(temp_analytics_dir, tmp_path):
    """Verify malformed JSON in calls.json falls back gracefully without raising."""
    bad_store_dir = tmp_path / "bad_store"
    bad_store_dir.mkdir()
    bad_json_file = bad_store_dir / "calls.json"
    bad_json_file.write_text("invalid json content")

    store = AnalyticsStore(report_dir=bad_store_dir)
    assert len(store.calls) == 0


def test_get_analytics_singleton(temp_analytics_dir):
    """Verify get_analytics singleton function behaves properly."""
    import analytics as analytics_mod

    # Reset singleton to force initialization
    analytics_mod._store = None

    store1 = get_analytics(temp_analytics_dir)
    assert store1 is not None
    assert store1.report_dir.resolve() == Path(temp_analytics_dir).resolve()

    # Get relative path to check logic
    analytics_mod._store = None
    store_rel = get_analytics("logs/temp_rel_analytics")
    assert store_rel.report_dir.is_absolute()

    # Clean up created dir if needed
    if store_rel.report_dir.exists():
        import shutil

        shutil.rmtree(store_rel.report_dir)

    # Getting it again should return the exact same instance
    analytics_mod._store = None
    s1 = get_analytics(temp_analytics_dir)
    s2 = get_analytics()
    assert s1 is s2
