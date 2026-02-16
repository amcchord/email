"""
Main wizard flow controller.

Orchestrates setup steps, tracks progress, and supports resume.
"""
import json
import os
import sys

from scripts.setup import ui

PROGRESS_FILE = "/opt/mail/.setup_progress"

STEPS = [
    ("preflight", "Pre-flight Checks"),
    ("system_deps", "System Dependencies"),
    ("google_cloud", "Google Cloud & OAuth"),
    ("domain", "Domain & SSL"),
    ("database", "Database Setup"),
    ("config", "Application Configuration"),
    ("app_build", "Build Application"),
    ("services", "Install Services"),
    ("verify", "Verification"),
]


class WizardState:
    """Persistent state shared across wizard steps."""

    def __init__(self):
        self.project_root = "/opt/mail"
        # Detected system info
        self.os_id = ""  # e.g. "debian", "ubuntu", "fedora"
        self.os_version = ""
        self.pkg_manager = ""  # "apt", "dnf", "pacman"
        # Google Cloud
        self.gcloud_project_id = ""
        self.google_client_id = ""
        self.google_client_secret = ""
        # Domain
        self.domain = ""
        self.use_https = True
        # Database
        self.db_user = "mailapp"
        self.db_password = ""
        self.db_name = "maildb"
        self.db_host = "localhost"
        self.db_port = "5432"
        # Config
        self.secret_key = ""
        self.encryption_key = ""
        self.admin_username = "admin"
        self.admin_password = ""
        self.claude_api_key = ""
        self.redis_url = "redis://localhost:6379/0"
        # Tracking
        self.completed_steps: list[str] = []

    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    def origin(self) -> str:
        scheme = "https" if self.use_https else "http"
        return f"{scheme}://{self.domain}"

    def redirect_uri(self) -> str:
        return f"{self.origin()}/api/auth/google/callback"

    def save(self):
        """Save progress to disk."""
        data = {
            "completed_steps": self.completed_steps,
            "domain": self.domain,
            "use_https": self.use_https,
            "gcloud_project_id": self.gcloud_project_id,
            "google_client_id": self.google_client_id,
            "db_user": self.db_user,
            "db_name": self.db_name,
            "db_host": self.db_host,
            "db_port": self.db_port,
            "os_id": self.os_id,
            "pkg_manager": self.pkg_manager,
            "admin_username": self.admin_username,
            "redis_url": self.redis_url,
        }
        try:
            with open(PROGRESS_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    def load(self) -> bool:
        """Load previous progress. Returns True if progress was found."""
        if not os.path.exists(PROGRESS_FILE):
            return False
        try:
            with open(PROGRESS_FILE) as f:
                data = json.load(f)
            self.completed_steps = data.get("completed_steps", [])
            self.domain = data.get("domain", "")
            self.use_https = data.get("use_https", True)
            self.gcloud_project_id = data.get("gcloud_project_id", "")
            self.google_client_id = data.get("google_client_id", "")
            self.db_user = data.get("db_user", "mailapp")
            self.db_name = data.get("db_name", "maildb")
            self.db_host = data.get("db_host", "localhost")
            self.db_port = data.get("db_port", "5432")
            self.os_id = data.get("os_id", "")
            self.pkg_manager = data.get("pkg_manager", "")
            self.admin_username = data.get("admin_username", "admin")
            self.redis_url = data.get("redis_url", "redis://localhost:6379/0")
            return len(self.completed_steps) > 0
        except (json.JSONDecodeError, OSError):
            return False

    def clear(self):
        """Remove progress file."""
        self.completed_steps = []
        try:
            os.remove(PROGRESS_FILE)
        except OSError:
            pass


def run_wizard():
    """Run the full interactive setup wizard."""
    ui.show_banner()

    state = WizardState()
    has_progress = state.load()

    # Ask about resuming if previous progress exists
    start_from = 0
    if has_progress and state.completed_steps:
        completed_names = []
        for step_id, step_name in STEPS:
            if step_id in state.completed_steps:
                completed_names.append(step_name)

        if completed_names:
            ui.info(f"Found previous progress: {len(completed_names)} step(s) completed.")
            for name in completed_names:
                ui.success(name)
            ui.console.print()

            action = ui.ask_select(
                "How would you like to proceed?",
                choices=[
                    {"name": "Resume from where I left off", "value": "resume"},
                    {"name": "Start over from the beginning", "value": "restart"},
                    {"name": "Jump to a specific step", "value": "jump"},
                ],
            )

            if action == "restart":
                state.clear()
                state = WizardState()
                start_from = 0
            elif action == "jump":
                step_choices = [
                    {"name": f"{i+1}. {name}", "value": i}
                    for i, (_, name) in enumerate(STEPS)
                ]
                start_from = ui.ask_select("Jump to step:", choices=step_choices)
            else:
                # Find first incomplete step
                for i, (step_id, _) in enumerate(STEPS):
                    if step_id not in state.completed_steps:
                        start_from = i
                        break
                else:
                    start_from = len(STEPS)

    # Build step tracker
    tracker = ui.StepTracker(STEPS)
    for step_id in state.completed_steps:
        tracker.set_status(step_id, "completed")

    # Import step runners
    from scripts.setup.steps import preflight
    from scripts.setup.steps import system_deps
    from scripts.setup.steps import google_cloud
    from scripts.setup.steps import config as config_step
    from scripts.setup.steps import database
    from scripts.setup.steps import application
    from scripts.setup.steps import services
    from scripts.setup.steps import verify

    step_runners = {
        "preflight": preflight.run,
        "system_deps": system_deps.run,
        "google_cloud": google_cloud.run,
        "domain": config_step.run_domain,
        "database": database.run,
        "config": config_step.run_config,
        "app_build": application.run,
        "services": services.run,
        "verify": verify.run,
    }

    # Run steps
    for i in range(start_from, len(STEPS)):
        step_id, step_name = STEPS[i]

        tracker.set_status(step_id, "in_progress")
        tracker.display()

        try:
            runner = step_runners[step_id]
            result = runner(state)

            if result == "skip":
                tracker.set_status(step_id, "skipped")
                ui.info(f"Skipped: {step_name}")
            else:
                tracker.set_status(step_id, "completed")
                if step_id not in state.completed_steps:
                    state.completed_steps.append(step_id)
                state.save()
                ui.step_done(f"Step {i + 1} complete: {step_name}")

        except KeyboardInterrupt:
            ui.console.print()
            ui.warning("Setup interrupted. Progress has been saved.")
            ui.info("Run the wizard again to resume from this step.")
            state.save()
            sys.exit(130)

        except Exception as exc:
            tracker.set_status(step_id, "failed")
            ui.step_failed(f"Step {i + 1} failed: {step_name}")
            ui.error(str(exc))
            ui.console.print()

            action = ui.ask_select(
                "What would you like to do?",
                choices=[
                    {"name": "Retry this step", "value": "retry"},
                    {"name": "Skip this step and continue", "value": "skip"},
                    {"name": "Quit (progress saved)", "value": "quit"},
                ],
            )

            if action == "retry":
                # Decrement i to retry (handled by re-running the loop iteration)
                # We can't easily re-enter the loop, so just recurse the step
                try:
                    runner = step_runners[step_id]
                    result = runner(state)
                    tracker.set_status(step_id, "completed")
                    if step_id not in state.completed_steps:
                        state.completed_steps.append(step_id)
                    state.save()
                    ui.step_done(f"Step {i + 1} complete: {step_name}")
                except Exception as retry_exc:
                    ui.error(f"Retry also failed: {retry_exc}")
                    ui.warning("Skipping this step.")
                    tracker.set_status(step_id, "skipped")
            elif action == "skip":
                tracker.set_status(step_id, "skipped")
            else:
                state.save()
                sys.exit(1)

    # Final summary
    ui.console.print()
    tracker.display()
    show_completion(state)


def show_completion(state: WizardState):
    """Show final completion message."""
    url = state.origin() if state.domain else "https://your-domain.com"

    ui.console.print(
        ui.Panel(
            f"[bold green]Setup Complete![/bold green]\n\n"
            f"Your mail app is ready at: [bold cyan]{url}[/bold cyan]\n\n"
            f"[bold]Next steps:[/bold]\n"
            f"  1. Log in with your admin account\n"
            f"  2. Connect a Gmail account via Settings\n"
            f"  3. Configure AI preferences in Admin panel\n\n"
            f"[bold]Useful commands:[/bold]\n"
            f"  [cyan]bash scripts/restart.sh[/cyan]         Restart all services\n"
            f"  [cyan]bash scripts/install.sh --verify[/cyan] Run health checks\n"
            f"  [cyan]sudo systemctl status mailapp[/cyan]   Check API status\n"
            f"  [cyan]sudo journalctl -u mailapp -f[/cyan]   View API logs",
            title="[bold white]All Done[/bold white]",
            border_style="green",
            padding=(1, 2),
        )
    )

    # Clean up progress file on full completion
    try:
        os.remove(PROGRESS_FILE)
    except OSError:
        pass


def run_verify_only():
    """Run just the verification checks."""
    ui.show_banner()
    ui.console.print("[bold]Running health checks...[/bold]")
    ui.console.print()

    state = WizardState()
    state.load()

    # If we have no domain from progress, try to read from .env
    if not state.domain:
        env_file = "/opt/mail/.env"
        if os.path.exists(env_file):
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("ALLOWED_ORIGINS="):
                        origin = line.split("=", 1)[1].strip()
                        # Extract domain from origin URL
                        domain = origin.replace("https://", "").replace("http://", "")
                        state.domain = domain
                        state.use_https = origin.startswith("https")
                    elif line.startswith("DATABASE_URL="):
                        pass  # Could parse but not needed for verify
                    elif line.startswith("GOOGLE_CLIENT_ID="):
                        state.google_client_id = line.split("=", 1)[1].strip()

    from scripts.setup.steps import verify
    verify.run(state)
