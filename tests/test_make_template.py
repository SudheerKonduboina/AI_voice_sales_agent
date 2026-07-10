"""Tests for make_template.py."""

import importlib
import os


def test_make_template():
    # Import and reload to record main-process coverage
    import crm.make_template

    importlib.reload(crm.make_template)

    # Verify template was created
    assert os.path.exists("leads_template.xlsx")

    # Cleanup template file
    os.remove("leads_template.xlsx")
