"""Explicit opt-in; creates labelled real rows/objects and never deletes them."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(os.getenv("RUN_SUPABASE_INTEGRATION_TESTS") != "1", reason="real Supabase test is opt-in")
def test_real_supabase_end_to_end(tmp_path):
    from tests.conftest import integration_environment

    config = integration_environment()
    video = os.getenv("SUPABASE_TEST_VIDEO")
    if not all(config.values()) or not video or not Path(video).is_file():
        pytest.skip("Supabase settings and SUPABASE_TEST_VIDEO are required")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "verify_supabase.py"), "--video", video],
        cwd=root, env={**os.environ, **config}, capture_output=True, text=True, encoding="utf-8", timeout=240,
    )
    # The script only emits a redacted report; never emit arbitrary stderr here.
    assert result.returncode == 0, "Supabase E2E failed; inspect .venv/supabase-e2e-last.json (redacted)"
    report = json.loads(result.stdout)
    assert report["passed"] and report["restart_persistence"]
