"""
api.py -- FastAPI service for n8n orchestration and dashboard.
"""

from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "crm"))
import excel_crm
from analytics import get_analytics
from call_service import create_conversation, finalize_call, run_scripted_call
from llm_client import LLMError
from logger_setup import get_logger, log_exception, next_request_id

logger = get_logger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "config.yaml"
DASHBOARD_DIR = BASE_DIR / "dashboard" / "dist"
_STARTUP_TIME = time.time()

app = FastAPI(title="AI Voice Sales Agent API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    req_id = next_request_id()
    request.state.request_id = req_id
    start = time.perf_counter()
    logger.info("[%s] %s %s", req_id, request.method, request.url.path)
    try:
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "[%s] %s %s -> %d (%.0f ms)",
            req_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        log_exception(
            logger,
            "[%s] %s %s failed after %.0f ms: %s",
            req_id,
            request.method,
            request.url.path,
            elapsed_ms,
            e,
        )
        raise


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


@app.on_event("startup")
def startup_event():
    from config_validator import ConfigError, validate_config
    from env_validator import EnvironmentValidationError, validate_environment

    try:
        cfg = load_config()

        validate_config(cfg)
        logger.info("Configuration validated successfully.")

        # Validate environment
        warnings = validate_environment(cfg, BASE_DIR)
        for warning in warnings:
            logger.warning(warning)
        logger.info("Environment validated successfully.")
    except ConfigError as e:
        logger.critical("Configuration validation failed: %s", e)
        sys.exit(1)
    except EnvironmentValidationError as e:
        logger.critical("Environment validation failed: %s", e)
        sys.exit(1)
    except Exception as e:
        logger.critical("Unexpected error during startup validation: %s", e, exc_info=True)
        sys.exit(1)


class CallRequest(BaseModel):
    lead_id: str
    mode: str = "simulate"


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch unhandled exceptions -- log full traceback, return friendly JSON."""
    req_id = getattr(request.state, "request_id", "UNKNOWN")
    log_exception(logger, "[%s] Unhandled exception: %s", req_id, exc)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "request_id": req_id},
    )


@app.get("/health")
def health():
    """Subsystem health check -- returns status of each critical component."""
    checks: dict[str, dict] = {}

    # Config check
    try:
        cfg = load_config()
        from config_validator import validate_config

        validate_config(cfg)
        checks["config"] = {"ok": True, "detail": "all required keys present"}
    except Exception as e:
        checks["config"] = {"ok": False, "detail": str(e)}

    # CRM check
    try:
        excel_path = str(BASE_DIR / cfg["crm"]["excel_path"])
        leads = excel_crm.get_all_leads(excel_path, cfg["crm"]["sheet_name"])
        checks["crm"] = {"ok": True, "detail": f"{len(leads)} leads loaded"}
    except Exception as e:
        checks["crm"] = {"ok": False, "detail": str(e)}

    # Ollama check
    try:
        ollama_url = os.environ.get("OLLAMA_BASE_URL") or cfg.get("llm", {}).get(
            "ollama_base_url", "http://localhost:11434"
        )
        if not (ollama_url.startswith("http://") or ollama_url.startswith("https://")):
            raise ValueError("Invalid URL scheme")
        req = urllib.request.Request(f"{ollama_url}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2):  # nosec B310
            checks["ollama"] = {"ok": True, "detail": f"reachable at {ollama_url}"}
    except Exception:
        checks["ollama"] = {"ok": False, "detail": "connection refused or timed out"}

    # Knowledge base check
    try:
        kb_path = BASE_DIR / cfg["company"]["knowledge_base_path"]
        if kb_path.exists():
            kb_size = kb_path.stat().st_size
            checks["knowledge_base"] = {"ok": True, "detail": f"{kb_size} bytes"}
        else:
            checks["knowledge_base"] = {"ok": False, "detail": "file not found"}
    except Exception as e:
        checks["knowledge_base"] = {"ok": False, "detail": str(e)}

    # Logs dir check
    logs_dir = BASE_DIR / "logs"
    checks["logs_dir"] = {
        "ok": logs_dir.exists() and os.access(str(logs_dir), os.W_OK),
        "detail": f"{logs_dir} {'writable' if logs_dir.exists() else 'missing'}",
    }

    # Overall status
    all_ok = all(c["ok"] for c in checks.values())
    critical_ok = checks.get("config", {}).get("ok") and checks.get("crm", {}).get("ok")
    if all_ok:
        overall = "healthy"
    elif critical_ok:
        overall = "degraded"
    else:
        overall = "unhealthy"

    status_code = 200 if overall != "unhealthy" else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": overall,
            "uptime_seconds": round(time.time() - _STARTUP_TIME, 1),
            "version": "1.0.0",
            "checks": checks,
        },
    )


@app.get("/api/pending-leads")
@app.get("/pending-leads")
def pending_leads():
    cfg = load_config()
    excel_path = BASE_DIR / cfg["crm"]["excel_path"]
    leads = excel_crm.get_pending_leads(str(excel_path), cfg["crm"]["sheet_name"])
    return {"count": len(leads), "leads": leads}


@app.get("/api/leads")
def all_leads(
    status: str | None = Query(None),
    search: str | None = Query(None),
):
    cfg = load_config()
    excel_path = BASE_DIR / cfg["crm"]["excel_path"]
    leads = excel_crm.get_all_leads(str(excel_path), cfg["crm"]["sheet_name"])
    if status:
        leads = [lead for lead in leads if (lead.get("status") or "") == status]
    if search:
        q = search.lower()
        leads = [
            lead
            for lead in leads
            if q in str(lead.get("name", "")).lower()
            or q in str(lead.get("lead_id", "")).lower()
            or q in str(lead.get("phone", "")).lower()
        ]
    return {"count": len(leads), "leads": leads}


@app.get("/api/leads/{lead_id}")
def get_lead(lead_id: str):
    cfg = load_config()
    excel_path = BASE_DIR / cfg["crm"]["excel_path"]
    leads = excel_crm.get_all_leads(str(excel_path), cfg["crm"]["sheet_name"])
    lead = next((ld for ld in leads if ld["lead_id"] == lead_id), None)
    if not lead:
        raise HTTPException(404, f"Lead {lead_id} not found")
    return lead


@app.get("/api/analytics")
def analytics_report():
    cfg = load_config()
    report_dir = cfg.get("analytics", {}).get("report_dir", "logs/analytics")
    if not os.path.isabs(report_dir):
        report_dir = str(BASE_DIR / report_dir)
    store = get_analytics(report_dir)
    return store.generate_report()


@app.get("/api/analytics/calls")
def analytics_calls():
    cfg = load_config()
    report_dir = cfg.get("analytics", {}).get("report_dir", "logs/analytics")
    if not os.path.isabs(report_dir):
        report_dir = str(BASE_DIR / report_dir)
    store = get_analytics(report_dir)
    return {"calls": [c.__dict__ for c in store.calls]}


@app.get("/api/logs")
def tail_logs(lines: int = Query(100, ge=1, le=500)):
    log_path = BASE_DIR / "logs" / "agent.log"
    if not log_path.exists():
        return {"lines": []}
    with open(log_path, encoding="utf-8", errors="replace") as f:
        content = f.readlines()
    return {"lines": [ln.rstrip() for ln in content[-lines:]]}


@app.post("/api/call")
@app.post("/call")
def make_call(req: CallRequest, request: Request):
    req_id = getattr(request.state, "request_id", next_request_id())
    logger.info("[%s] Starting call lead_id=%s mode=%s", req_id, req.lead_id, req.mode)
    try:
        cfg = load_config()
        excel_path = BASE_DIR / cfg["crm"]["excel_path"]
        kb_path = BASE_DIR / cfg["company"]["knowledge_base_path"]

        leads = excel_crm.get_all_leads(str(excel_path), cfg["crm"]["sheet_name"])
        lead = next((ld for ld in leads if ld["lead_id"] == req.lead_id), None)
        if not lead:
            raise HTTPException(404, f"Lead {req.lead_id} not found")

        with open(kb_path, encoding="utf-8") as f:
            knowledge_base = f.read()

        if req.mode == "live":
            import asyncio

            from voice_pipeline import run_call

            convo = asyncio.run(run_call(lead, cfg, knowledge_base, str(BASE_DIR)))
            result = convo.extract_result()
        else:
            from simulate_call import AUTO_SCRIPT

            convo = create_conversation(lead, cfg, knowledge_base, str(BASE_DIR))
            result = run_scripted_call(convo, AUTO_SCRIPT)

        finalize_call(lead, convo, result, cfg, str(BASE_DIR))
        return {"lead_id": req.lead_id, **result.as_update_dict()}
    except HTTPException:
        raise
    except LLMError as e:
        log_exception(logger, "[%s] LLM error lead_id=%s: %s", req_id, req.lead_id, e)
        raise HTTPException(503, "LLM service unavailable -- please try again later") from e
    except Exception as e:
        log_exception(logger, "[%s] Call failed lead_id=%s: %s", req_id, req.lead_id, e)
        raise HTTPException(500, "Call processing failed -- see server logs") from e


@app.get("/api/meetings")
def meetings():
    """Return leads with booked meetings."""
    cfg = load_config()
    excel_path = str(BASE_DIR / cfg["crm"]["excel_path"])
    return {"meetings": excel_crm.get_meetings_scheduled(excel_path, cfg["crm"]["sheet_name"])}


@app.get("/api/transcript/{lead_id}")
def transcript(lead_id: str):
    """Return conversation summary and notes for a lead."""
    cfg = load_config()
    excel_path = str(BASE_DIR / cfg["crm"]["excel_path"])
    lead = excel_crm.get_lead_by_id(excel_path, lead_id, cfg["crm"]["sheet_name"])
    if not lead:
        raise HTTPException(404, f"Lead {lead_id} not found")
    return {
        "lead_id": lead_id,
        "conversation_summary": lead.get("conversation_summary", "") or "",
        "notes": lead.get("notes", "") or "",
        "status": lead.get("status", "") or "",
        "meeting_datetime": lead.get("meeting_datetime", "") or "",
    }


@app.get("/api/export")
def export_data():
    """Export all leads, analytics, and meetings as a single JSON download."""
    cfg = load_config()
    excel_path = str(BASE_DIR / cfg["crm"]["excel_path"])
    sheet_name = cfg["crm"]["sheet_name"]

    leads_data = excel_crm.get_all_leads(excel_path, sheet_name)
    meetings_data = excel_crm.get_meetings_scheduled(excel_path, sheet_name)

    report_dir = cfg.get("analytics", {}).get("report_dir", "logs/analytics")
    if not os.path.isabs(report_dir):
        report_dir = str(BASE_DIR / report_dir)
    analytics_data = get_analytics(report_dir).generate_report()

    import json as _json

    export = {
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "version": "1.0.0",
        "leads": leads_data,
        "meetings": meetings_data,
        "analytics": analytics_data,
    }
    content = _json.dumps(export, indent=2, default=str)
    return JSONResponse(
        content=_json.loads(content),
        headers={
            "Content-Disposition": "attachment; filename=sales-agent-export.json",
        },
    )


if DASHBOARD_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DASHBOARD_DIR / "assets"), name="assets")

    @app.get("/")
    @app.get("/dashboard")
    def dashboard():
        return FileResponse(DASHBOARD_DIR / "index.html")
