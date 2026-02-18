"""
Step 8: Service installation.

Generates and installs systemd unit files for mailapp, mailworker,
and configures Caddy. Enables and starts all services.
"""
import os
import time

from scripts.setup import ui


PROJECT_ROOT = "/opt/mail"

MAILAPP_SERVICE = """\
[Unit]
Description=Mail Client API
After=network.target postgresql.service redis-server.service
Requires=postgresql.service redis-server.service

[Service]
Type=simple
User=mailapp
Group=mailapp
WorkingDirectory={project_root}
ExecStart={project_root}/venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=3
Environment=PATH={project_root}/venv/bin:/usr/local/bin:/usr/bin
Environment=OAUTHLIB_RELAX_TOKEN_SCOPE=1

[Install]
WantedBy=multi-user.target
"""

MAILWORKER_SERVICE = """\
[Unit]
Description=Mail Client Background Worker
After=network.target postgresql.service redis-server.service mailapp.service
Requires=postgresql.service redis-server.service

[Service]
Type=simple
User=mailapp
Group=mailapp
WorkingDirectory={project_root}
ExecStart={project_root}/venv/bin/arq backend.workers.tasks.WorkerSettings
Restart=always
RestartSec=5
Environment=PATH={project_root}/venv/bin:/usr/local/bin:/usr/bin
Environment=OAUTHLIB_RELAX_TOKEN_SCOPE=1

[Install]
WantedBy=multi-user.target
"""

SYSTEMD_DIR = "/etc/systemd/system"


def _sudo_cmd(cmd: list[str]) -> list[str]:
    if os.geteuid() == 0:
        return cmd
    return ["sudo"] + cmd


def _service_is_active(service: str) -> bool:
    """Check if a systemd service is active."""
    result = ui.run_cmd(
        ["systemctl", "is-active", service],
        capture=True,
        check=False,
    )
    return result.returncode == 0 and "active" in (result.stdout or "")


def _service_exists(service: str) -> bool:
    """Check if a systemd unit file exists."""
    return os.path.exists(os.path.join(SYSTEMD_DIR, f"{service}.service"))


def install_service_file(name: str, content: str) -> bool:
    """Write a systemd service file."""
    target = os.path.join(SYSTEMD_DIR, f"{name}.service")

    # Check if identical file already exists
    if os.path.exists(target):
        with open(target) as f:
            existing = f.read()
        if existing.strip() == content.strip():
            ui.success(f"  {name}.service already up to date")
            return True

    ui.info(f"  Writing {target}...")

    # Write via sudo tee
    import subprocess
    proc = subprocess.Popen(
        _sudo_cmd(["tee", target]),
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    _, stderr = proc.communicate(input=content)

    if proc.returncode != 0:
        ui.error(f"  Failed to write {target}: {stderr}")
        return False

    ui.success(f"  Installed {name}.service")
    return True


def configure_caddy_service(state) -> bool:
    """Ensure Caddy service is configured with our Caddyfile."""
    ui.info("Configuring Caddy service...")

    # Check if Caddy has a systemd service
    if not _service_exists("caddy"):
        # Caddy installed from package usually has its own service
        # Check if the binary exists
        if not ui.cmd_exists("caddy"):
            ui.warning("Caddy not found. Skipping Caddy service configuration.")
            return False

    # Caddy v2 typically reads from /etc/caddy/Caddyfile
    # We need to either:
    # 1. Symlink our Caddyfile there
    # 2. Or modify the caddy service to point to our Caddyfile
    system_caddyfile = "/etc/caddy/Caddyfile"
    our_caddyfile = os.path.join(PROJECT_ROOT, "Caddyfile")

    if os.path.exists(our_caddyfile):
        # Create /etc/caddy directory if needed
        ui.run_cmd(
            _sudo_cmd(["mkdir", "-p", "/etc/caddy"]),
            capture=True,
            check=False,
        )

        # Copy our Caddyfile to the system location
        ui.run_cmd(
            _sudo_cmd(["cp", our_caddyfile, system_caddyfile]),
            capture=True,
            check=False,
        )
        ui.success(f"  Copied Caddyfile to {system_caddyfile}")

    # Create log directory
    ui.run_cmd(
        _sudo_cmd(["mkdir", "-p", "/var/log/caddy"]),
        capture=True,
        check=False,
    )

    return True


def run(state) -> str | None:
    """Run service installation step."""
    ui.step_header(
        8,
        "Install Services",
        "Generate systemd unit files, enable and start services",
    )

    project_root = PROJECT_ROOT

    # --- Generate and install service files ---
    ui.info("[bold]Installing systemd service files...[/bold]")
    ui.console.print()

    mailapp_content = MAILAPP_SERVICE.format(project_root=project_root)
    mailworker_content = MAILWORKER_SERVICE.format(project_root=project_root)

    # Show service files
    show_details = ui.ask_confirm("Show service file contents?", default=False)
    if show_details:
        ui.console.print(
            ui.Panel(mailapp_content, title="[bold]mailapp.service[/bold]", border_style="blue")
        )
        ui.console.print(
            ui.Panel(mailworker_content, title="[bold]mailworker.service[/bold]", border_style="blue")
        )

    install_service_file("mailapp", mailapp_content)
    install_service_file("mailworker", mailworker_content)

    # --- Configure Caddy ---
    ui.console.print()
    configure_caddy_service(state)

    # --- Reload systemd ---
    ui.console.print()
    ui.info("Reloading systemd daemon...")
    ui.run_cmd(
        _sudo_cmd(["systemctl", "daemon-reload"]),
        capture=True,
        check=False,
    )
    ui.success("systemd daemon reloaded")

    # --- Enable services ---
    ui.console.print()
    ui.info("[bold]Enabling services...[/bold]")

    services_to_enable = ["mailapp", "mailworker", "caddy"]

    # Also ensure PostgreSQL and Redis are enabled
    pg_service = "postgresql"
    redis_service = "redis-server"
    if state.pkg_manager in ("dnf", "pacman"):
        redis_service = "redis"

    all_services = [pg_service, redis_service] + services_to_enable

    for svc in all_services:
        result = ui.run_cmd(
            _sudo_cmd(["systemctl", "enable", svc]),
            capture=True,
            check=False,
        )
        if result.returncode == 0:
            ui.success(f"  Enabled {svc}")
        else:
            ui.warning(f"  Could not enable {svc}")

    # --- Start services ---
    ui.console.print()
    start_now = ui.ask_confirm("Start all services now?", default=True)

    if start_now:
        ui.info("[bold]Starting services...[/bold]")

        # Start in dependency order
        start_order = [pg_service, redis_service, "mailapp", "mailworker", "caddy"]

        for svc in start_order:
            ui.info(f"  Starting {svc}...")
            result = ui.run_cmd(
                _sudo_cmd(["systemctl", "restart", svc]),
                capture=True,
                check=False,
            )
            if result.returncode == 0:
                # Give it a moment to start
                time.sleep(1)
                if _service_is_active(svc):
                    ui.success(f"  {svc} is running")
                else:
                    ui.warning(f"  {svc} started but may not be ready yet")
            else:
                stderr = (result.stderr or "").strip()
                ui.error(f"  Failed to start {svc}: {stderr}")

        # Write build version
        build_version_file = os.path.join(PROJECT_ROOT, ".build_version")
        with open(build_version_file, "w") as f:
            f.write(str(int(time.time())))

    # --- Status check ---
    ui.console.print()
    ui.info("[bold]Service Status:[/bold]")

    status_results = []
    for svc in all_services:
        if _service_is_active(svc):
            status_results.append((svc, "pass", "Running"))
        else:
            # Check if it at least exists
            if _service_exists(svc):
                status_results.append((svc, "warn", "Installed but not running"))
            else:
                status_results.append((svc, "fail", "Not installed"))

    ui.checks_table("Service Status", status_results)

    return None
