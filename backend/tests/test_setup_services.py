import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# Read as text: the installer module imports setup-only UI dependencies.
INSTALLER = REPO_ROOT / "scripts" / "setup" / "steps" / "services.py"
RUNBOOK = REPO_ROOT / "docs" / "operations" / "RUNBOOK.md"
README = REPO_ROOT / "README.md"


def _bounds(path: Path) -> tuple[int, int]:
    text = path.read_text()
    graceful = re.search(r"--timeout-graceful-shutdown (\d+)", text)
    stop = re.search(r"^TimeoutStopSec=(\d+)$", text, re.MULTILINE)
    assert graceful and stop
    return int(graceful.group(1)), int(stop.group(1))


def test_mailapp_unit_drains_before_systemd_force_kills():
    graceful, stop = _bounds(INSTALLER)

    # Lifespan shutdown runs after the drain and can take up to 5 seconds.
    assert stop > graceful + 5


def test_documented_mailapp_unit_values_match_the_installer():
    expected = _bounds(INSTALLER)

    assert _bounds(README) == expected
    assert _bounds(RUNBOOK) == expected
