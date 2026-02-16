"""
Step 2: System dependencies installation.

Installs PostgreSQL, Redis, Caddy, Node.js, and build essentials
using the detected package manager. Idempotent — skips what is
already installed.
"""
import os
import grp
import pwd

from rich.progress import Progress, SpinnerColumn, TextColumn

from scripts.setup import ui


def _sudo_cmd(cmd: list[str]) -> list[str]:
    """Prepend sudo if not running as root."""
    if os.geteuid() == 0:
        return cmd
    return ["sudo"] + cmd


def _is_installed(binary: str) -> bool:
    """Check if a binary is on PATH."""
    return ui.cmd_exists(binary)


def _user_exists(username: str) -> bool:
    """Check if a system user exists."""
    try:
        pwd.getpwnam(username)
        return True
    except KeyError:
        return False


def _group_exists(groupname: str) -> bool:
    """Check if a system group exists."""
    try:
        grp.getgrnam(groupname)
        return True
    except KeyError:
        return False


# ---------------------------------------------------------------------------
# Per-package-manager install functions
# ---------------------------------------------------------------------------
def _install_apt(packages: list[str], label: str) -> bool:
    """Install packages via apt."""
    ui.info(f"Installing {label} via apt...")
    try:
        ui.run_cmd(_sudo_cmd(["apt-get", "update", "-qq"]), capture=True, check=True)
        ui.run_cmd(
            _sudo_cmd(["apt-get", "install", "-y", "-qq"] + packages),
            capture=True,
            check=True,
        )
        return True
    except Exception as exc:
        ui.error(f"apt install failed: {exc}")
        return False


def _install_dnf(packages: list[str], label: str) -> bool:
    """Install packages via dnf."""
    ui.info(f"Installing {label} via dnf...")
    try:
        ui.run_cmd(
            _sudo_cmd(["dnf", "install", "-y", "-q"] + packages),
            capture=True,
            check=True,
        )
        return True
    except Exception as exc:
        ui.error(f"dnf install failed: {exc}")
        return False


def _install_pacman(packages: list[str], label: str) -> bool:
    """Install packages via pacman."""
    ui.info(f"Installing {label} via pacman...")
    try:
        ui.run_cmd(
            _sudo_cmd(["pacman", "-S", "--noconfirm", "--needed"] + packages),
            capture=True,
            check=True,
        )
        return True
    except Exception as exc:
        ui.error(f"pacman install failed: {exc}")
        return False


def _install_packages(pkg_manager: str, packages: dict[str, list[str]], label: str) -> bool:
    """Install packages using the detected package manager.

    packages is a dict: {"apt": [...], "dnf": [...], "pacman": [...]}
    """
    pkg_list = packages.get(pkg_manager, [])
    if not pkg_list:
        ui.warning(f"No package names defined for {pkg_manager}. Install {label} manually.")
        return False

    installers = {
        "apt": _install_apt,
        "dnf": _install_dnf,
        "pacman": _install_pacman,
    }
    installer = installers.get(pkg_manager)
    if not installer:
        ui.warning(f"Unsupported package manager: {pkg_manager}. Install {label} manually.")
        return False

    return installer(pkg_list, label)


# ---------------------------------------------------------------------------
# Individual component installers
# ---------------------------------------------------------------------------
def install_build_essentials(pkg_manager: str) -> bool:
    """Install build tools and common dependencies."""
    if _is_installed("gcc") and _is_installed("make"):
        ui.success("Build essentials already installed")
        return True

    return _install_packages(pkg_manager, {
        "apt": ["build-essential", "curl", "wget", "gnupg2", "lsb-release",
                "software-properties-common", "ca-certificates"],
        "dnf": ["gcc", "gcc-c++", "make", "curl", "wget", "gnupg2", "ca-certificates"],
        "pacman": ["base-devel", "curl", "wget"],
    }, "build essentials")


def install_python(pkg_manager: str) -> bool:
    """Ensure Python 3.11+ with venv support."""
    # Check if already good
    ver = ui.get_cmd_output(["python3", "--version"])
    if ver:
        import re
        match = re.search(r'(\d+)\.(\d+)', ver)
        if match and int(match.group(1)) >= 3 and int(match.group(2)) >= 11:
            # Also check for venv
            check = ui.run_cmd(["python3", "-m", "venv", "--help"], capture=True, check=False)
            if check.returncode == 0:
                ui.success(f"Python already installed: {ver.strip()}")
                return True

    return _install_packages(pkg_manager, {
        "apt": ["python3", "python3-venv", "python3-pip", "python3-dev"],
        "dnf": ["python3", "python3-pip", "python3-devel"],
        "pacman": ["python", "python-pip"],
    }, "Python 3")


def install_nodejs(pkg_manager: str) -> bool:
    """Ensure Node.js 18+ and npm."""
    ver = ui.get_cmd_output(["node", "--version"])
    if ver:
        import re
        match = re.search(r'(\d+)', ver)
        if match and int(match.group(1)) >= 18:
            ui.success(f"Node.js already installed: {ver.strip()}")
            return True

    if pkg_manager == "apt":
        # Use NodeSource repository for latest Node.js
        ui.info("Adding NodeSource repository for Node.js 20...")
        try:
            ui.run_cmd(
                "curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -",
                shell=True,
                capture=True,
                check=True,
            )
            return _install_apt(["nodejs"], "Node.js")
        except Exception:
            ui.warning("NodeSource setup failed, trying system packages...")
            return _install_apt(["nodejs", "npm"], "Node.js")
    elif pkg_manager == "dnf":
        ui.info("Adding NodeSource repository for Node.js 20...")
        try:
            ui.run_cmd(
                "curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo -E bash -",
                shell=True,
                capture=True,
                check=True,
            )
            return _install_dnf(["nodejs"], "Node.js")
        except Exception:
            return _install_dnf(["nodejs", "npm"], "Node.js")
    elif pkg_manager == "pacman":
        return _install_pacman(["nodejs", "npm"], "Node.js")

    ui.warning("Install Node.js 18+ manually: https://nodejs.org/")
    return False


def install_postgresql(pkg_manager: str) -> bool:
    """Ensure PostgreSQL is installed."""
    if _is_installed("psql") and _is_installed("pg_isready"):
        ui.success("PostgreSQL already installed")
        return True

    success = _install_packages(pkg_manager, {
        "apt": ["postgresql", "postgresql-client", "libpq-dev"],
        "dnf": ["postgresql-server", "postgresql", "postgresql-devel"],
        "pacman": ["postgresql", "postgresql-libs"],
    }, "PostgreSQL")

    if success and pkg_manager == "dnf":
        # Fedora/RHEL requires explicit init
        ui.info("Initializing PostgreSQL database...")
        ui.run_cmd(
            _sudo_cmd(["postgresql-setup", "--initdb"]),
            capture=True,
            check=False,
        )

    return success


def install_redis(pkg_manager: str) -> bool:
    """Ensure Redis is installed."""
    if _is_installed("redis-server") or _is_installed("redis"):
        ui.success("Redis already installed")
        return True

    return _install_packages(pkg_manager, {
        "apt": ["redis-server"],
        "dnf": ["redis"],
        "pacman": ["redis"],
    }, "Redis")


def install_caddy(pkg_manager: str) -> bool:
    """Ensure Caddy web server is installed."""
    if _is_installed("caddy"):
        ui.success("Caddy already installed")
        return True

    if pkg_manager == "apt":
        ui.info("Adding Caddy repository...")
        try:
            cmds = [
                "sudo apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https",
                "curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg 2>/dev/null || true",
                "curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null",
                "sudo apt-get update -qq",
                "sudo apt-get install -y -qq caddy",
            ]
            for cmd in cmds:
                ui.run_cmd(cmd, shell=True, capture=True, check=True)
            return True
        except Exception as exc:
            ui.error(f"Caddy install failed: {exc}")
            return False
    elif pkg_manager == "dnf":
        ui.info("Adding Caddy COPR repository...")
        try:
            ui.run_cmd(
                _sudo_cmd(["dnf", "copr", "enable", "-y", "@caddy/caddy"]),
                capture=True,
                check=True,
            )
            return _install_dnf(["caddy"], "Caddy")
        except Exception:
            pass
    elif pkg_manager == "pacman":
        return _install_pacman(["caddy"], "Caddy")

    # Fallback: direct binary install
    ui.info("Installing Caddy via official installer...")
    try:
        ui.run_cmd(
            "curl -1sLf 'https://caddyserver.com/api/download?os=linux&arch=amd64' | sudo tee /usr/bin/caddy >/dev/null && sudo chmod +x /usr/bin/caddy",
            shell=True,
            capture=True,
            check=True,
        )
        return True
    except Exception:
        ui.warning("Install Caddy manually: https://caddyserver.com/docs/install")
        return False


def create_system_user() -> bool:
    """Create the mailapp system user if it doesn't exist."""
    if _user_exists("mailapp"):
        ui.success("System user 'mailapp' already exists")
        return True

    ui.info("Creating system user 'mailapp'...")
    try:
        ui.run_cmd(
            _sudo_cmd([
                "useradd", "--system", "--home-dir", "/opt/mail",
                "--shell", "/usr/sbin/nologin", "--create-home",
                "mailapp",
            ]),
            capture=True,
            check=True,
        )
        ui.success("Created system user 'mailapp'")
        return True
    except Exception as exc:
        ui.error(f"Failed to create user: {exc}")
        return False


def setup_directories() -> bool:
    """Create required directories with correct ownership."""
    dirs = [
        "/opt/mail",
        "/opt/mail/data",
        "/opt/mail/data/attachments",
        "/var/log/caddy",
    ]

    for d in dirs:
        if not os.path.exists(d):
            try:
                os.makedirs(d, exist_ok=True)
                ui.success(f"Created {d}")
            except PermissionError:
                ui.run_cmd(
                    _sudo_cmd(["mkdir", "-p", d]),
                    capture=True,
                    check=False,
                )

    # Set ownership for /opt/mail if mailapp user exists
    if _user_exists("mailapp"):
        try:
            ui.run_cmd(
                _sudo_cmd(["chown", "-R", "mailapp:mailapp", "/opt/mail"]),
                capture=True,
                check=False,
            )
        except Exception:
            pass

    ui.success("Directories ready")
    return True


def enable_services(pkg_manager: str):
    """Enable and start PostgreSQL and Redis via systemd."""
    services_to_enable = []

    # PostgreSQL
    pg_service = "postgresql"
    if pkg_manager == "apt":
        pg_service = "postgresql"
    elif pkg_manager == "dnf":
        pg_service = "postgresql"

    services_to_enable.append(pg_service)

    # Redis
    redis_service = "redis-server"
    if pkg_manager in ("dnf", "pacman"):
        redis_service = "redis"
    services_to_enable.append(redis_service)

    for svc in services_to_enable:
        ui.info(f"Enabling and starting {svc}...")
        ui.run_cmd(
            _sudo_cmd(["systemctl", "enable", "--now", svc]),
            capture=True,
            check=False,
        )


# ---------------------------------------------------------------------------
# Main step runner
# ---------------------------------------------------------------------------
def run(state) -> str | None:
    """Run system dependency installation."""
    ui.step_header(
        2,
        "System Dependencies",
        "Installing PostgreSQL, Redis, Caddy, Node.js, and build tools",
    )

    pkg_manager = state.pkg_manager
    if not pkg_manager:
        ui.warning("Could not detect package manager.")
        manual = ui.ask_confirm(
            "Skip automatic installation? (you'll need to install dependencies manually)",
            default=False,
        )
        if manual:
            return "skip"
        pkg_manager = ui.ask_select(
            "Select your package manager:",
            choices=["apt", "dnf", "pacman", "skip"],
        )
        if pkg_manager == "skip":
            return "skip"
        state.pkg_manager = pkg_manager

    # Show what will be installed
    components = [
        ("Build essentials", _is_installed("gcc")),
        ("Python 3.11+", _is_installed("python3")),
        ("Node.js 18+", _is_installed("node")),
        ("PostgreSQL", _is_installed("psql")),
        ("Redis", _is_installed("redis-server") or _is_installed("redis")),
        ("Caddy", _is_installed("caddy")),
    ]

    to_install = [name for name, installed in components if not installed]
    already_done = [name for name, installed in components if installed]

    if already_done:
        ui.info("Already installed: " + ", ".join(already_done))
    if to_install:
        ui.info("Will install: " + ", ".join(to_install))
    else:
        ui.success("All system dependencies are already installed!")
        create_system_user()
        setup_directories()
        enable_services(pkg_manager)
        return None

    ui.console.print()
    proceed = ui.ask_confirm(f"Install {len(to_install)} package(s)?", default=True)
    if not proceed:
        return "skip"

    # Install each component
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=ui.console,
    ) as progress:
        task = progress.add_task("Installing system dependencies...", total=6)

        progress.update(task, description="[cyan]Build essentials...")
        install_build_essentials(pkg_manager)
        progress.advance(task)

        progress.update(task, description="[cyan]Python...")
        install_python(pkg_manager)
        progress.advance(task)

        progress.update(task, description="[cyan]Node.js...")
        install_nodejs(pkg_manager)
        progress.advance(task)

        progress.update(task, description="[cyan]PostgreSQL...")
        install_postgresql(pkg_manager)
        progress.advance(task)

        progress.update(task, description="[cyan]Redis...")
        install_redis(pkg_manager)
        progress.advance(task)

        progress.update(task, description="[cyan]Caddy...")
        install_caddy(pkg_manager)
        progress.advance(task)

    ui.console.print()

    # Create user and directories
    create_system_user()
    setup_directories()

    # Enable services
    enable_services(pkg_manager)

    # Final check
    results = []
    for name, check_bin in [
        ("Python", "python3"),
        ("Node.js", "node"),
        ("PostgreSQL", "psql"),
        ("Redis", "redis-server"),
        ("Caddy", "caddy"),
    ]:
        # Re-check redis with alternate name
        found = _is_installed(check_bin)
        if not found and check_bin == "redis-server":
            found = _is_installed("redis")
        status = "pass" if found else "fail"
        results.append((name, status, "Installed" if found else "Not found"))

    ui.checks_table("Post-Install Check", results)
    return None
