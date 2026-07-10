"""
call_runner.py -- processes every Pending lead in the CRM in one pass.
"""

from __future__ import annotations

import argparse
import os
import sys

import yaml

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "crm"))
import excel_crm
from call_service import create_conversation, finalize_call, run_scripted_call
from logger_setup import get_logger, log_exception

logger = get_logger(__name__)

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def process_lead(lead: dict, cfg: dict, knowledge_base: str, mode: str) -> dict:
    if mode == "live":
        import asyncio

        from voice_pipeline import run_call

        convo = asyncio.run(run_call(lead, cfg, knowledge_base, BASE_DIR))
        result = convo.extract_result()
        finalize_call(lead, convo, result, cfg, BASE_DIR)
        return result.as_update_dict()

    from simulate_call import AUTO_SCRIPT

    convo = create_conversation(lead, cfg, knowledge_base, BASE_DIR)
    result = run_scripted_call(convo, AUTO_SCRIPT)
    finalize_call(lead, convo, result, cfg, BASE_DIR)
    return result.as_update_dict()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["simulate", "live"], default="simulate")
    parser.add_argument("--config", default=os.path.join(BASE_DIR, "config", "config.yaml"))
    args = parser.parse_args()

    cfg = load_config(args.config)
    try:
        from config_validator import ConfigError, validate_config

        validate_config(cfg)
    except ConfigError as e:
        print(f"Configuration Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Validate Environment
    from pathlib import Path

    try:
        from env_validator import EnvironmentValidationError, validate_environment

        warnings = validate_environment(cfg, Path(BASE_DIR))
        for warning in warnings:
            logger.warning(warning)
    except EnvironmentValidationError as e:
        logger.error("Environment Validation Failed: %s", e)
        print(f"Environment Error: {e}", file=sys.stderr)
        sys.exit(1)

    excel_path = os.path.join(BASE_DIR, cfg["crm"]["excel_path"])
    kb_path = os.path.join(BASE_DIR, cfg["company"]["knowledge_base_path"])
    with open(kb_path, encoding="utf-8") as f:
        knowledge_base = f.read()

    pending = excel_crm.get_pending_leads(excel_path, cfg["crm"]["sheet_name"])
    logger.info("Found %d pending lead(s)", len(pending))

    for lead in pending:
        logger.info("Calling %s (%s) [%s mode]", lead["name"], lead["phone"], args.mode)
        try:
            updates = process_lead(lead, cfg, knowledge_base, args.mode)
        except Exception as e:
            log_exception(logger, "Call failed for %s: %s", lead["lead_id"], e)
            updates = {"status": "No Answer", "notes": f"Call attempt errored: {e}"}
            excel_crm.update_lead(excel_path, lead["lead_id"], updates, cfg["crm"]["sheet_name"])
            continue
        logger.info("  -> %s / %s", updates.get("status"), updates.get("qualification", "n/a"))

    logger.info("Done. CRM updated at %s", excel_path)


if __name__ == "__main__":
    main()
