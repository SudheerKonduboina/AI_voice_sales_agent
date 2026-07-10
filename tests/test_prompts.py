"""Tests for prompts.py."""

import prompts


def test_build_system_prompt_with_facts():
    prompt = prompts.build_system_prompt(
        company_name="Acme",
        caller_purpose="demo",
        lead_name="Jane",
        knowledge_base="## Pricing\n$19/mo",
        conversation_summary="Discussed pricing.",
        customer_facts="## Important customer facts\n- Team size: 6 people",
    )
    assert "Acme" in prompt
    assert "Discussed pricing" in prompt
    assert "Team size: 6" in prompt
    assert "Pricing" in prompt


def test_build_extraction_prompt():
    prompt = prompts.build_extraction_prompt("Agent: Hi\nProspect: Hello")
    assert "TRANSCRIPT:" in prompt
    assert "Agent: Hi" in prompt


def test_prompt_version_in_system_prompt():
    """Prompt-Version header must appear in the system prompt."""
    prompt = prompts.build_system_prompt(
        company_name="Acme",
        caller_purpose="demo",
        lead_name="Jane",
        knowledge_base="## Pricing\n$19/mo",
    )
    assert f"# Prompt-Version: {prompts.PROMPT_VERSION}" in prompt


def test_get_prompt_version():
    """get_prompt_version() returns the current version string."""
    version = prompts.get_prompt_version()
    assert isinstance(version, str)
    assert version == prompts.PROMPT_VERSION
