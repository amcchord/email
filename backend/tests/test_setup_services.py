import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# Read as text: the installer module imports setup-only UI dependencies.
INSTALLER = REPO_ROOT / "scripts" / "setup" / "steps" / "services.py"
CADDYFILE = REPO_ROOT / "Caddyfile"
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


def test_caddy_holds_api_requests_for_longer_than_a_restart_can_take():
    _, stop = _bounds(INSTALLER)

    # Both proxies to uvicorn, so a restart cannot fail a terminal's check-in.
    holds = re.findall(r"lb_try_duration (\d+)s", CADDYFILE.read_text())
    assert len(holds) == 2
    assert all(int(hold) > stop for hold in holds)
