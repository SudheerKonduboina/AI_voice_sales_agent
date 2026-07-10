"""Integration tests for api.py using fastapi.testclient."""

import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

# Mock llama_cpp module first before importing api to avoid loading real GGUF
sys_mock = MagicMock()
import sys  # noqa: E402

sys.modules["llama_cpp"] = sys_mock

from api import BASE_DIR, app, load_config, startup_event  # noqa: E402
from config_validator import ConfigError  # noqa: E402
from conversation import ConversationResult  # noqa: E402
from env_validator import EnvironmentValidationError  # noqa: E402
from llm_client import LLMError, LLMUsage  # noqa: E402


@pytest.fixture(autouse=True)
def reset_analytics_singleton():
    """Reset the analytics singleton to prevent cross-test leakage."""
    import analytics

    analytics._store = None
    yield
    analytics._store = None


@pytest.fixture
def client(temp_excel, tmp_path):
    """Fixture to provide a TestClient and configure app CONFIG_PATH to temp_excel."""
    # We can patch load_config to return config pointing to temp_excel
    mock_config = {
        "company": {
            "name": "Acme Test",
            "caller_purpose": "demo",
            "knowledge_base_path": "config/knowledge_base.md",
        },
        "crm": {
            "excel_path": os.path.relpath(temp_excel, BASE_DIR),
            "sheet_name": "Leads",
        },
        "llm": {
            "provider": "ollama",
            "temperature": 0.5,
            "max_history_turns": 4,
        },
        "rag": {
            "top_k": 2,
            "min_score": 0.01,
        },
        "call": {
            "max_call_duration_seconds": 300,
            "max_silence_seconds": 10,
        },
        "analytics": {
            "report_dir": "logs/analytics",  # Use relative path to cover relative analytics dir checks
        },
    }

    mock_usage = MagicMock(prompt_tokens=10, completion_tokens=5, inference_ms=50.0)
    mock_extract_json = json.dumps(
        {
            "status": "Booked",
            "qualification": "Hot",
            "conversation_summary": "Simulated call outcome description.",
            "customer_requirements": "CRM solution",
            "objections_raised": "pricing tiers",
            "follow_up_date": "",
            "meeting_datetime": "2026-07-15 10:00",
            "notes": "highly interested",
        }
    )

    with patch("api.load_config", return_value=mock_config):
        # Patch env validation to return immediately, avoiding slow network timeouts
        with patch("env_validator.validate_environment", return_value=[]):
            with patch(
                "llm_client.chat_with_usage",
                return_value=("Hello, let's schedule a demo.", mock_usage),
            ):
                with patch("llm_client.chat", return_value=mock_extract_json):
                    yield TestClient(app)


def test_load_config_actual():
    """Verify load_config reads and parses config yaml file successfully."""
    dummy_yaml = "test: value"
    with patch("builtins.open", mock_open(read_data=dummy_yaml)):
        cfg = load_config()
        assert cfg == {"test": "value"}


def test_health_endpoint_healthy(client):
    """Verify health endpoint checks are overall successful when reachable."""
    mock_resp = MagicMock()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["checks"]["crm"]["ok"] is True
        assert data["checks"]["config"]["ok"] is True


def test_health_endpoint_degraded(client):
    """Verify health endpoint returns degraded status when non-critical check fails."""
    # Force urllib.request.urlopen to fail to make Ollama unreachable
    with patch("urllib.request.urlopen", side_effect=Exception("Ollama down")):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["checks"]["ollama"]["ok"] is False


def test_health_endpoint_unhealthy(client):
    """Verify health endpoint checks return 503 when critical systems fail."""
    # Force excel_crm.get_all_leads to raise error to trigger unhealthy state
    with patch("excel_crm.get_all_leads", side_effect=Exception("Database down")):
        response = client.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["checks"]["crm"]["ok"] is False


def test_health_kb_missing_and_config_except(client):
    """Verify health endpoint handles missing KB and validator exceptions gracefully."""
    # Patch exists to return False specifically for knowledge_base to cover line 163
    orig_exists = Path.exists

    def conditional_exists(self_path, *args, **kwargs):
        if "knowledge_base" in str(self_path):
            return False
        return orig_exists(self_path, *args, **kwargs)

    with patch("config_validator.validate_config", side_effect=Exception("validation error")):
        with patch.object(Path, "exists", conditional_exists):
            response = client.get("/health")
            assert response.status_code == 503
            data = response.json()
            assert data["checks"]["config"]["ok"] is False
            assert data["checks"]["knowledge_base"]["ok"] is False
            assert data["checks"]["knowledge_base"]["detail"] == "file not found"


def test_health_kb_exception(client):
    """Verify health endpoint handles KB check exceptions gracefully (covers line 164-165)."""

    # Patch exists to raise PermissionError specifically for knowledge_base
    def conditional_exists_error(self_path, *args, **kwargs):
        if "knowledge_base" in str(self_path):
            raise PermissionError("Access denied")
        return True

    with patch.object(Path, "exists", conditional_exists_error):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["checks"]["knowledge_base"]["ok"] is False
        assert "Access denied" in data["checks"]["knowledge_base"]["detail"]


def test_health_endpoint_invalid_scheme(client):
    """Verify health endpoint rejects invalid url schemes for Ollama check."""
    invalid_config = {
        "company": {
            "name": "Acme Test",
            "caller_purpose": "demo",
            "knowledge_base_path": "config/knowledge_base.md",
        },
        "crm": {
            "excel_path": "crm/leads.xlsx",
            "sheet_name": "Leads",
        },
        "llm": {
            "provider": "ollama",
            "ollama_base_url": "ftp://invalid-scheme:11434",
        },
        "analytics": {
            "report_dir": "logs/analytics",
        },
    }
    with patch("api.load_config", return_value=invalid_config):
        response = client.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["checks"]["ollama"]["ok"] is False
        assert "connection refused" in data["checks"]["ollama"]["detail"]


def test_pending_leads(client):
    response = client.get("/api/pending-leads")
    assert response.status_code == 200
    data = response.json()
    assert "leads" in data
    assert "count" in data


def test_all_leads_with_filters(client):
    response = client.get("/api/leads")
    assert response.status_code == 200
    all_data = response.json()
    assert all_data["count"] > 0

    response_pending = client.get("/api/leads?status=Pending")
    assert response_pending.status_code == 200

    response_search = client.get("/api/leads?search=L001")
    assert response_search.status_code == 200
    assert any(lead["lead_id"] == "L001" for lead in response_search.json()["leads"])


def test_get_lead_by_id(client):
    # Success
    response = client.get("/api/leads/L001")
    assert response.status_code == 200
    assert response.json()["lead_id"] == "L001"

    # Not found
    response_404 = client.get("/api/leads/LXXX")
    assert response_404.status_code == 404


def test_analytics_endpoints(client):
    # Generate report using patched api.get_analytics
    with patch("api.get_analytics") as mock_get_analytics:
        mock_analytics = MagicMock()
        mock_analytics.generate_report.return_value = {"total_calls": 5}
        mock_analytics.calls = [MagicMock()]
        mock_get_analytics.return_value = mock_analytics

        response = client.get("/api/analytics")
        assert response.status_code == 200
        assert response.json()["total_calls"] == 5

        response_calls = client.get("/api/analytics/calls")
        assert response_calls.status_code == 200
        assert "calls" in response_calls.json()


def test_tail_logs_endpoint(client):
    # Mock log file presence and read
    mock_log_lines = ["line1\n", "line2\n"]

    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data="".join(mock_log_lines))):
            response = client.get("/api/logs?lines=2")
            assert response.status_code == 200
            assert response.json()["lines"] == ["line1", "line2"]


def test_tail_logs_endpoint_missing(client):
    with patch("pathlib.Path.exists", return_value=False):
        response = client.get("/api/logs")
        assert response.status_code == 200
        assert response.json()["lines"] == []


def test_meetings_endpoint(client):
    response = client.get("/api/meetings")
    assert response.status_code == 200
    assert "meetings" in response.json()


def test_transcript_endpoint(client):
    # Success L001
    response = client.get("/api/transcript/L001")
    assert response.status_code == 200
    data = response.json()
    assert "conversation_summary" in data

    # Not found LXXX
    response_404 = client.get("/api/transcript/LXXX")
    assert response_404.status_code == 404


def test_make_call_simulation(client):
    """Verify simulation mode scripted call pipeline executes."""
    payload = {"lead_id": "L001", "mode": "simulate"}
    response = client.post("/api/call", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "Booked"


@patch("voice_pipeline.run_call")
def test_make_call_live(mock_run_call, client):
    """Verify live mode call pipeline logic runs and handles finalization."""

    async def mock_run_call_impl(*args, **kwargs):
        mock_result = ConversationResult(
            status="Called",
            qualification="Warm",
            conversation_summary="Live call outcome description.",
            customer_requirements="None",
            objections_raised="",
            follow_up_date="",
            meeting_datetime="",
            notes="Notes from live call.",
        )

        mock_convo = MagicMock()
        mock_convo.started_at = datetime.now()
        mock_convo.total_usage = LLMUsage(inference_ms=100.0, prompt_tokens=10, completion_tokens=5)
        mock_convo.turns = 1
        mock_convo.tool_executor = None
        mock_convo.extract_result.return_value = mock_result
        return mock_convo

    mock_run_call.side_effect = mock_run_call_impl

    payload = {"lead_id": "L001", "mode": "live"}
    response = client.post("/api/call", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "Called"


def test_make_call_not_found(client):
    payload = {"lead_id": "LXXX", "mode": "simulate"}
    response = client.post("/api/call", json=payload)
    assert response.status_code == 404


def test_make_call_llm_error(client):
    payload = {"lead_id": "L001", "mode": "simulate"}
    with patch("llm_client.chat_with_usage", side_effect=LLMError("LLM offline")):
        response = client.post("/api/call", json=payload)
        assert response.status_code == 503


def test_make_call_general_error(client):
    payload = {"lead_id": "L001", "mode": "simulate"}
    with patch("llm_client.chat_with_usage", side_effect=RuntimeError("Connection lost")):
        response = client.post("/api/call", json=payload)
        assert response.status_code == 500


def test_global_exception_handler(temp_excel):
    """Trigger unhandled exception to test global exception response."""
    # Initialize TestClient with raise_server_exceptions=False to let Starlette handle it
    non_raising_client = TestClient(app, raise_server_exceptions=False)
    with patch("api.load_config", side_effect=ValueError("Unhandled syntax crash")):
        response = non_raising_client.get("/api/pending-leads")
        assert response.status_code == 500
        assert "Internal server error" in response.json()["error"]


def test_startup_event_success():
    with patch("api.load_config") as mock_load:
        with patch("config_validator.validate_config") as mock_val_cfg:
            with patch(
                "env_validator.validate_environment", return_value=["warn1"]
            ) as mock_val_env:
                startup_event()
                assert mock_load.called
                assert mock_val_cfg.called
                assert mock_val_env.called


def test_startup_event_config_error():
    with patch("api.load_config"):
        with patch("config_validator.validate_config", side_effect=ConfigError("Invalid keys")):
            with patch("sys.exit") as mock_exit:
                startup_event()
                mock_exit.assert_called_once_with(1)


def test_startup_event_env_error():
    with patch("api.load_config"):
        with patch("config_validator.validate_config"):
            with patch(
                "env_validator.validate_environment",
                side_effect=EnvironmentValidationError("Missing excel"),
            ):
                with patch("sys.exit") as mock_exit:
                    startup_event()
                    mock_exit.assert_called_once_with(1)


def test_startup_event_unexpected_exception():
    with patch("api.load_config", side_effect=RuntimeError("unexpected startup crash")):
        with patch("sys.exit") as mock_exit:
            startup_event()
            mock_exit.assert_called_once_with(1)


def test_dashboard_route(client):
    """Test dashboard index response when dashboard assets exist."""
    with patch("pathlib.Path.exists", return_value=True):
        # Mock FileResponse return using HTMLResponse so starlette doesn't json serialize
        with patch("api.FileResponse") as mock_file_resp:
            mock_file_resp.return_value = HTMLResponse(content="dashboard index content")
            response = client.get("/dashboard")
            assert response.status_code == 200
            assert response.text == "dashboard index content"


def test_export_endpoint(client):
    """Test /api/export returns valid JSON with leads, meetings, analytics."""
    response = client.get("/api/export")
    assert response.status_code == 200
    data = response.json()
    assert "exported_at" in data
    assert "version" in data
    assert "leads" in data
    assert "meetings" in data
    assert "analytics" in data
    assert isinstance(data["leads"], list)
    assert isinstance(data["meetings"], list)
    assert isinstance(data["analytics"], dict)
    # Verify Content-Disposition header for download
    assert "attachment" in response.headers.get("content-disposition", "")
