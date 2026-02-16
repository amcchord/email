"""
Step 1: Pre-flight checks.

Detects OS, checks installed software versions, checks port availability,
and displays a summary table.
"""
import os
import platform
import re
import socket

from scripts.setup import ui


def detect_os() -> tuple[str, str, str]:
    """Detect OS distribution. Returns (os_id, os_version, pkg_manager)."""
    os_id = "unknown"
    os_version = ""
    pkg_manager = ""

    # Try /etc/os-release first (works on most modern Linux)
    if os.path.exists("/etc/os-release"):
        with open("/etc/os-release") as f:
            lines = f.read()
        id_match = re.search(r'^ID=(.+)$', lines, re.MULTILINE)
        version_match = re.search(r'^VERSION_ID="?([^"]+)"?$', lines, re.MULTILINE)
        id_like_match = re.search(r'^ID_LIKE=(.+)$', lines, re.MULTILINE)

        if id_match:
            os_id = id_match.group(1).strip().strip('"').lower()
        if version_match:
            os_version = version_match.group(1).strip()

        # Determine package manager from ID or ID_LIKE
        id_like = ""
        if id_like_match:
            id_like = id_like_match.group(1).strip().strip('"').lower()

        if os_id in ("debian", "ubuntu", "linuxmint", "pop", "elementary", "zorin"):
            pkg_manager = "apt"
        elif "debian" in id_like or "ubuntu" in id_like:
            pkg_manager = "apt"
        elif os_id in ("fedora", "rhel", "centos", "rocky", "alma", "ol"):
            pkg_manager = "dnf"
        elif "fedora" in id_like or "rhel" in id_like:
            pkg_manager = "dnf"
        elif os_id in ("arch", "manjaro", "endeavouros"):
            pkg_manager = "pacman"
        elif "arch" in id_like:
            pkg_manager = "pacman"
        elif os_id in ("opensuse", "sles"):
            pkg_manager = "zypper"
    elif platform.system() == "Darwin":
        os_id = "macos"
        os_version = platform.mac_ver()[0]
        pkg_manager = "brew"

    return os_id, os_version, pkg_manager


def check_version(cmd: list[str], pattern: str = r'(\d+\.\d+[\.\d]*)') -> str:
    """Try to get a version string from a command's output."""
    output = ui.get_cmd_output(cmd)
    if not output:
        return ""
    match = re.search(pattern, output)
    if match:
        return match.group(1)
    return ""


def check_port(port: int) -> bool:
    """Check if a port is available (not in use)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(1)
        result = sock.connect_ex(("127.0.0.1", port))
        # connect_ex returns 0 if connection succeeds (port in use)
        return result != 0
    except Exception:
        return True
    finally:
        sock.close()


def check_port_in_use(port: int) -> bool:
    """Check if a port is actively in use (for services that should be running)."""
    return not check_port(port)


def run(state) -> str | None:
    """Run pre-flight checks."""
    ui.step_header(1, "Pre-flight Checks", "Detecting your system and checking requirements")

    # --- OS Detection ---
    os_id, os_version, pkg_manager = detect_os()
    state.os_id = os_id
    state.os_version = os_version
    state.pkg_manager = pkg_manager

    os_display = f"{os_id}"
    if os_version:
        os_display += f" {os_version}"
    ui.info(f"Detected OS: [bold]{os_display}[/bold]")
    if pkg_manager:
        ui.info(f"Package manager: [bold]{pkg_manager}[/bold]")
    else:
        ui.warning("Could not detect package manager. You may need to install dependencies manually.")
    ui.console.print()

    # --- Check software versions ---
    results = []

    # Python
    python_ver = check_version(["python3", "--version"])
    if python_ver:
        major_minor = python_ver.split(".")
        if len(major_minor) >= 2 and int(major_minor[0]) >= 3 and int(major_minor[1]) >= 11:
            results.append(("Python 3.11+", "pass", f"v{python_ver}"))
        else:
            results.append(("Python 3.11+", "fail", f"v{python_ver} (too old)"))
    else:
        results.append(("Python 3.11+", "fail", "Not found"))

    # Node.js
    node_ver = check_version(["node", "--version"])
    if node_ver:
        major = int(node_ver.split(".")[0])
        if major >= 18:
            results.append(("Node.js 18+", "pass", f"v{node_ver}"))
        else:
            results.append(("Node.js 18+", "warn", f"v{node_ver} (recommend 18+)"))
    else:
        results.append(("Node.js 18+", "fail", "Not found"))

    # npm
    npm_ver = check_version(["npm", "--version"])
    if npm_ver:
        results.append(("npm", "pass", f"v{npm_ver}"))
    else:
        results.append(("npm", "fail", "Not found"))

    # PostgreSQL
    pg_ver = check_version(["pg_config", "--version"])
    if not pg_ver:
        pg_ver = check_version(["psql", "--version"])
    if pg_ver:
        results.append(("PostgreSQL", "pass", f"v{pg_ver}"))
    else:
        results.append(("PostgreSQL", "fail", "Not found"))

    # Redis
    redis_ver = check_version(["redis-server", "--version"])
    if redis_ver:
        results.append(("Redis", "pass", f"v{redis_ver}"))
    else:
        results.append(("Redis", "fail", "Not found"))

    # Caddy
    caddy_ver = check_version(["caddy", "version"])
    if caddy_ver:
        results.append(("Caddy", "pass", f"v{caddy_ver}"))
    else:
        results.append(("Caddy", "fail", "Not found"))

    # Git
    git_ver = check_version(["git", "--version"])
    if git_ver:
        results.append(("Git", "pass", f"v{git_ver}"))
    else:
        results.append(("Git", "warn", "Not found (optional)"))

    # gcloud CLI
    gcloud_ver = check_version(["gcloud", "--version"])
    if gcloud_ver:
        results.append(("gcloud CLI", "pass", f"v{gcloud_ver}"))
    else:
        results.append(("gcloud CLI", "info", "Not installed (will set up in Step 3)"))

    ui.checks_table("Software Requirements", results)

    # --- Check ports ---
    port_results = []
    port_checks = [
        (80, "HTTP (Caddy)"),
        (443, "HTTPS (Caddy)"),
        (5432, "PostgreSQL"),
        (6379, "Redis"),
        (8000, "FastAPI backend"),
    ]

    for port, desc in port_checks:
        available = check_port(port)
        if available:
            port_results.append((f"Port {port} ({desc})", "pass", "Available"))
        else:
            # Port in use is fine for services that are already running
            if port in (5432, 6379):
                port_results.append(
                    (f"Port {port} ({desc})", "pass", "In use (service running)")
                )
            else:
                port_results.append(
                    (f"Port {port} ({desc})", "warn", "In use (may need to stop existing service)")
                )

    ui.checks_table("Port Availability", port_results)

    # --- Check if running as root / sudo available ---
    is_root = os.geteuid() == 0
    can_sudo = False
    if not is_root:
        can_sudo = ui.cmd_exists("sudo")

    if is_root:
        ui.info("Running as [bold]root[/bold]")
    elif can_sudo:
        ui.info("Running as user, [bold]sudo[/bold] is available")
    else:
        ui.warning("Not running as root and sudo not available. Some steps may fail.")

    ui.console.print()

    # Check for missing critical dependencies
    missing_critical = []
    for name, status, detail in results:
        if status == "fail" and "optional" not in detail.lower():
            missing_critical.append(name)

    if missing_critical:
        ui.warning(f"Missing: {', '.join(missing_critical)}")
        ui.info("These will be installed in the next step.")
    else:
        ui.success("All critical dependencies are present!")

    ui.console.print()
    return None
