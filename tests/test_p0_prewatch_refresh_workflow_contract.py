"""Static workflow-contract regression; does not simulate hosted GitHub Actions."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MORNING = ROOT / ".github" / "workflows" / "rikstoto-morning.yml"
PILOT = ROOT / ".github" / "workflows" / "prewatch-collector-refresh.yml"


def _persist_section():
    source = MORNING.read_text(encoding="utf-8")
    return source.split("\n  persist:\n", 1)[1]


def test_failed_collector_cannot_publish_fresh_source_release():
    """Require successful full-day job before either archive or meeting feeds."""
    section = _persist_section()
    condition = re.search(r"(?m)^    if: (.+)$", section)
    assert condition, "persist job has no conditional gate"
    expression = condition.group(1)
    assert "needs['full-day'].result == 'success'" in expression
    assert "github.event_name == 'schedule'" in expression
    assert "github.event_name == 'workflow_dispatch'" in expression
    assert "inputs.persist_archive == true" in expression
    assert "always()" not in expression
    assert section.index("if: ") < section.index("Publish date release")
    assert "Publish immutable read-only Pre-Watch meeting feeds" in section


def test_failed_capture_keeps_diagnostic_artifact():
    """The failure evidence must survive even when persist is skipped."""
    source = MORNING.read_text(encoding="utf-8")
    full_day = source.split("\n  full-day:\n", 1)[1].split("\n  persist:\n", 1)[0]
    assert "name: Save daily evidence and full programs" in full_day
    assert "if: always()" in full_day
    assert "name: Flag incomplete or unsuccessful collection" in full_day
    assert "steps.harvest.outcome == 'failure'" in full_day


def test_pilot_still_dispatches_existing_collector_only():
    source = PILOT.read_text(encoding="utf-8")
    assert "gh workflow run rikstoto-morning.yml" in source
    assert "--field \"source_origin=prewatch_pilot\"" in source
    assert "--field \"persist_archive=true\"" in source
    assert "Collector dispatch ACK" in source
    assert "NOT proof of completed source capture" in source
    assert "date(2026, 11, 23), date(2026, 12, 8)" in source
    assert "timezone: Europe/Oslo" in source


def test_readiness_requires_actual_official_roster_observation():
    """Never promote dispatcher time to official roster freshness."""
    source = PILOT.read_text(encoding="utf-8")
    assert "official starts/driverChanges observations" in source
    assert "never from this trigger clock" in source
    assert "snapshot" not in source.lower().split("gh workflow run", 1)[1].split("echo \"Collector", 1)[0]
