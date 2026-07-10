"""
simulate_call.py -- run a full sales call in your terminal, keyboard in / text
out, using the exact same Conversation + CRM logic the real voice pipeline
uses. This is the fastest way to test prompts, objection handling, and the
Excel write-back without setting up telephony, Whisper, or Piper.

Usage:
    cd agent
    python3 simulate_call.py --lead-id L001
    python3 simulate_call.py --lead-id L001 --auto     # scripted demo, no typing needed
"""

from __future__ import annotations

import argparse
import os
import sys

import yaml

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "crm"))
import excel_crm
from call_service import create_conversation, finalize_call
from logger_setup import get_logger

logger = get_logger(__name__)

AUTO_SCRIPT = [
    "Yeah, this is she, go ahead.",
    "We're currently just using spreadsheets, it's getting messy honestly.",
    "About 6 people on the sales team.",
    "What's the pricing look like?",
    "That's not bad actually. Yeah I could do a quick call.",
    "Thursday afternoon works, say 3pm?",
    "Sounds good, thanks!",
]


def load_config(path: str) -> dict:
    """Load YAML configuration from disk."""
    with open(path) as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lead-id", required=True)
    parser.add_argument(
        "--config", default=os.path.join(os.path.dirname(__file__), "..", "config", "config.yaml")
    )
    parser.add_argument(
        "--auto", action="store_true", help="run a scripted demo conversation instead of typing"
    )
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

        base_dir_path = Path(os.path.dirname(__file__)).resolve().parent
        warnings = validate_environment(cfg, base_dir_path)
        for warning in warnings:
            print(f"Warning: {warning}", file=sys.stderr)
    except EnvironmentValidationError as e:
        print(f"Environment Error: {e}", file=sys.stderr)
        sys.exit(1)

    excel_path = os.path.join(os.path.dirname(__file__), "..", cfg["crm"]["excel_path"])
    kb_path = os.path.join(os.path.dirname(__file__), "..", cfg["company"]["knowledge_base_path"])

    leads = excel_crm.get_all_leads(excel_path, cfg["crm"]["sheet_name"])
    lead = next((ld for ld in leads if ld["lead_id"] == args.lead_id), None)
    if not lead:
        logger.error("No lead with ID %r found in %s", args.lead_id, excel_path)
        return

    with open(kb_path) as f:
        knowledge_base = f.read()

    convo = create_conversation(
        lead, cfg, knowledge_base, os.path.join(os.path.dirname(__file__), "..")
    )

    logger.info("=== Simulated call to %s (%s) ===", lead["name"], lead["phone"])
    print(f"\n=== Simulated call to {lead['name']} ({lead['phone']}) ===\n")

    # Opening line with streaming support
    print("Agent: ", end="", flush=True)
    streamed = False

    def stream_cb(chunk):
        nonlocal streamed
        streamed = True
        print(chunk, end="", flush=True)

    opening = convo.agent_opening_line(callback=stream_cb)
    if not streamed:
        print(opening, end="", flush=True)
    print("\n")

    script_iter = iter(AUTO_SCRIPT)
    while not convo.ended:
        if args.auto:
            try:
                user_text = next(script_iter)
            except StopIteration:
                break
            print(f"Prospect: {user_text}")
        else:
            user_text = input("Prospect: ").strip()
            if not user_text:
                continue
            if user_text.lower() in ("quit", "exit"):
                break

        print("Agent: ", end="", flush=True)
        streamed = False

        def stream_cb_turn(chunk):
            nonlocal streamed
            streamed = True
            print(chunk, end="", flush=True)

        reply = convo.respond_to(user_text, callback=stream_cb_turn)
        if not streamed:
            print(reply, end="", flush=True)
        print("\n")

    print("\n=== Call ended, extracting outcome ===")
    logger.info("Call ended, extracting outcome")
    result = convo.extract_result()
    print(result)

    finalize_call(lead, convo, result, cfg, os.path.join(os.path.dirname(__file__), ".."))
    logger.info("CRM updated for lead %s", args.lead_id)
    print(f"\nCRM updated for lead {args.lead_id} in {excel_path}")


if __name__ == "__main__":
    main()
