"""
analytics.py -- call analytics tracking and automatic report generation.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from logger_setup import get_logger

logger = get_logger(__name__)


@dataclass
class CallMetrics:
    """Metrics captured for a single call."""

    lead_id: str
    lead_name: str
    status: str
    qualification: str
    duration_seconds: float
    inference_time_seconds: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    retrieval_count: int = 0
    objections: str = ""
    meeting_booked: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class AnalyticsStore:
    """In-memory + file-backed analytics store."""

    calls: list[CallMetrics] = field(default_factory=list)
    report_dir: Path = field(default_factory=lambda: Path("logs/analytics"))

    def __post_init__(self) -> None:
        self.report_dir = Path(self.report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self._load()

    def _store_path(self) -> Path:
        return self.report_dir / "calls.json"

    def _load(self) -> None:
        path = self._store_path()
        if not path.exists():
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.calls = [CallMetrics(**c) for c in data.get("calls", [])]
            logger.info("Loaded %d call records from analytics store", len(self.calls))
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("Could not load analytics store: %s", e)

    def _save(self) -> None:
        path = self._store_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"calls": [asdict(c) for c in self.calls]}, f, indent=2)

    def record_call(self, metrics: CallMetrics) -> None:
        """Record a completed call."""
        self.calls.append(metrics)
        self._save()
        logger.info(
            "Analytics recorded: lead=%s status=%s duration=%.1fs",
            metrics.lead_id,
            metrics.status,
            metrics.duration_seconds,
        )
        self.generate_report()

    def generate_report(self) -> dict[str, Any]:
        """Generate summary analytics report."""
        if not self.calls:
            report: dict[str, Any] = {
                "total_calls": 0,
                "generated_at": datetime.now().isoformat(),
            }
        else:
            total = len(self.calls)
            successful = [c for c in self.calls if c.status in ("Booked", "Called")]
            booked = [c for c in self.calls if c.status == "Booked" or c.meeting_booked]
            durations = [c.duration_seconds for c in self.calls if c.duration_seconds > 0]
            inference_times = [
                c.inference_time_seconds for c in self.calls if c.inference_time_seconds > 0
            ]
            objections = sum(
                1 for c in self.calls if c.objections and c.objections.lower() not in ("none", "")
            )

            # Qualification breakdown
            qualifications: dict[str, int] = {}
            for c in self.calls:
                qualifications[c.qualification] = qualifications.get(c.qualification, 0) + 1

            # Status breakdown
            per_status: dict[str, int] = {}
            for c in self.calls:
                per_status[c.status] = per_status.get(c.status, 0) + 1

            # Rates
            success_rate = round(len(successful) / total * 100, 1) if total else 0.0
            qualified_count = sum(1 for c in self.calls if c.qualification in ("Hot", "Warm"))
            qualification_rate = round(qualified_count / total * 100, 1) if total else 0.0

            # Average response time in ms (from inference_time_seconds)
            avg_response_ms = (
                round(sum(inference_times) / len(inference_times) * 1000, 1)
                if inference_times
                else 0.0
            )

            report = {
                "generated_at": datetime.now().isoformat(),
                "total_calls": total,
                "successful_calls": len(successful),
                "booked_meetings": len(booked),
                "success_rate_pct": success_rate,
                "qualification_rate_pct": qualification_rate,
                "average_duration_seconds": round(sum(durations) / len(durations), 2)
                if durations
                else 0,
                "average_inference_time_seconds": round(
                    sum(inference_times) / len(inference_times), 2
                )
                if inference_times
                else 0,
                "average_response_time_ms": avg_response_ms,
                "total_prompt_tokens": sum(c.prompt_tokens for c in self.calls),
                "total_completion_tokens": sum(c.completion_tokens for c in self.calls),
                "retrieval_usage_total": sum(c.retrieval_count for c in self.calls),
                "objections_count": objections,
                "qualifications": qualifications,
                "per_status_breakdown": per_status,
            }

        report_path = self.report_dir / "report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        logger.info("Analytics report generated: %s", report_path)
        return report


# Module-level singleton
_store: AnalyticsStore | None = None


def get_analytics(report_dir: str | None = None) -> AnalyticsStore:
    """Return the shared analytics store."""
    global _store
    if _store is None:
        base = Path(__file__).resolve().parent.parent
        path = Path(report_dir) if report_dir else base / "logs" / "analytics"
        if not path.is_absolute():
            path = base / path
        _store = AnalyticsStore(report_dir=path)
    return _store
