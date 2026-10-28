"""Execute the actual Phase B Actions summary script without a live network.

A green workflow must clearly disclose no-op/blocked/diagnostic-only status.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

WORKFLOW = (
    Path(__file__).parent.parent / ".github/workflows/awatch-selective-win.yml"
)


def _summary_script():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    fragment = workflow.split("      - name: Summarize without BET authorization", 1)[1]
    fragment = fragment.split("      - uses: actions/upload-artifact", 1)[0]
    source = fragment.split("          python - <<'PY'\n", 1)[1]
    source = source.split("          PY\n", 1)[0]
    return textwrap.dedent(source)


def _run_summary(tmp_path, payload):
    summary = tmp_path / "summary.md"
    if payload is not None:
        output = tmp_path / "output"
        output.mkdir()
        (output / "awatch_win_diagnostic.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
    env = dict(os.environ, GITHUB_STEP_SUMMARY=str(summary))
    result = subprocess.run(
        [sys.executable, "-c", _summary_script()],
        cwd=tmp_path, env=env, text=True, capture_output=True, check=False,
    )
    return result, summary.read_text(encoding="utf-8")


@pytest.mark.parametrize(("state", "selected", "due", "probed"), [
    ("NO_QUALIFIED_A_WATCH", 0, 0, 0),
    ("QUALIFIED_A_WATCH_NOT_DUE", 1, 0, 0),
    ("DUE_BUT_NO_SOURCE_PROBE", 1, 1, 0),
    ("DUE_SOURCE_INCOMPLETE_OR_BLOCKED", 1, 1, 1),
    ("SOURCE_CANDIDATES_UNVERIFIED_NOT_BET", 1, 1, 1),
])
def test_actual_actions_summary_never_mislabels_receipt_as_a_bet(
    tmp_path, state, selected, due, probed
):
    payload = {
        "probed_race_count": probed,
        "receipt": {
            "status": state, "selected_by_manual_prewatch_input": selected,
            "due_unique_races": due, "probes_attempted": probed,
            "due_terminal_counts": {},
        },
    }
    run, output = _run_summary(tmp_path, payload)
    assert run.returncode == 0, run.stderr
    assert f"Terminal diagnostic state: `{state}`" in output
    assert f"Source requests attempted: {probed}" in output
    assert "**BET_BLOCKED.**" in output
    assert "calibrated p(win)" in output
    assert "BET authorization: **YES**" not in output


def test_missing_diagnostic_is_reported_as_blocked_not_success(tmp_path):
    run, output = _run_summary(tmp_path, None)
    assert run.returncode == 0
    assert "BLOCKED: no diagnostic output" in output
    assert "Terminal diagnostic state:" not in output


def test_missing_receipt_is_not_counted_as_phase_b_completion(tmp_path):
    run, output = _run_summary(tmp_path, {"probed_race_count": 1})
    assert run.returncode == 0
    assert "BLOCKED: missing Phase B terminal receipt" in output
    assert "Terminal diagnostic state:" not in output
    assert "**BET_BLOCKED.**" in output
