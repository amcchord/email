"""
Rich console helpers for the setup wizard TUI.

Provides a consistent, beautiful interface with panels, banners,
status tables, step trackers, and prompt wrappers.
"""
import os
import subprocess
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.rule import Rule
from rich import box

from InquirerPy import inquirer
from InquirerPy.separator import Separator

console = Console()

# ---------------------------------------------------------------------------
# Status symbols
# ---------------------------------------------------------------------------
PASS = "[bold green]PASS[/bold green]"
FAIL = "[bold red]FAIL[/bold red]"
WARN = "[bold yellow]WARN[/bold yellow]"
SKIP = "[bold dim]SKIP[/bold dim]"
INFO = "[bold blue]INFO[/bold blue]"

CHECK = "[green]OK[/green]"
CROSS = "[red]FAIL[/red]"
BULLET = "[dim]-[/dim]"


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
BANNER_ART = r"""
  __  __       _ _     _
 |  \/  | __ _(_) |   / \   _ __  _ __
 | |\/| |/ _` | | |  / _ \ | '_ \| '_ \
 | |  | | (_| | | | / ___ \| |_) | |_) |
 |_|  |_|\__,_|_|_|/_/   \_\ .__/| .__/
                            |_|   |_|
"""


def show_banner():
    """Display the welcome banner."""
    banner_text = Text(BANNER_ART, style="bold cyan")
    console.print(banner_text)
    console.print(
        Panel(
            "[bold]Self-hosted, AI-augmented email client[/bold]\n"
            "Svelte 5 + FastAPI + PostgreSQL + Gmail API + Claude AI",
            title="[bold white]Setup Wizard[/bold white]",
            border_style="cyan",
            padding=(1, 2),
        )
    )
    console.print()


# ---------------------------------------------------------------------------
# Step tracking
# ---------------------------------------------------------------------------
class StepTracker:
    """Track and display wizard steps with status indicators."""

    def __init__(self, steps: list[tuple[str, str]]):
        """steps: list of (id, description) tuples."""
        self.steps = steps
        self.current_index = 0
        self.statuses: dict[str, str] = {}
        for step_id, _ in steps:
            self.statuses[step_id] = "pending"

    def set_status(self, step_id: str, status: str):
        self.statuses[step_id] = status

    def display(self):
        """Show the step progress bar."""
        parts = []
        for i, (step_id, desc) in enumerate(self.steps):
            status = self.statuses.get(step_id, "pending")
            if status == "completed":
                marker = "[green]>>>[/green]"
                style = "green"
            elif status == "in_progress":
                marker = "[cyan]>>>[/cyan]"
                style = "bold cyan"
            elif status == "failed":
                marker = "[red]>>>[/red]"
                style = "red"
            elif status == "skipped":
                marker = "[dim]>>>[/dim]"
                style = "dim"
            else:
                marker = "[dim]   [/dim]"
                style = "dim"

            num = f"[{style}]{i + 1}.[/{style}]"
            text = f"[{style}]{desc}[/{style}]"
            parts.append(f"  {marker} {num} {text}")

        content = "\n".join(parts)
        console.print(
            Panel(
                content,
                title="[bold]Progress[/bold]",
                border_style="blue",
                padding=(0, 1),
            )
        )
        console.print()


# ---------------------------------------------------------------------------
# Step headers and footers
# ---------------------------------------------------------------------------
def step_header(number: int, title: str, description: str = ""):
    """Display a step header."""
    console.print()
    console.print(Rule(f"[bold cyan]Step {number}: {title}[/bold cyan]", style="cyan"))
    if description:
        console.print(f"  [dim]{description}[/dim]")
    console.print()


def step_done(message: str = "Done"):
    """Display step completion."""
    console.print(f"  [bold green]{message}[/bold green]")
    console.print()


def step_failed(message: str = "Failed"):
    """Display step failure."""
    console.print(f"  [bold red]{message}[/bold red]")
    console.print()


# ---------------------------------------------------------------------------
# Status messages
# ---------------------------------------------------------------------------
def info(msg: str):
    console.print(f"  [blue][info][/blue]  {msg}")


def success(msg: str):
    console.print(f"  [green][ok][/green]    {msg}")


def warning(msg: str):
    console.print(f"  [yellow][warn][/yellow]  {msg}")


def error(msg: str):
    console.print(f"  [red][error][/red] {msg}")


# ---------------------------------------------------------------------------
# Check result table
# ---------------------------------------------------------------------------
def checks_table(title: str, results: list[tuple[str, str, str]]):
    """Display a table of check results.

    results: list of (name, status, detail) where status is
    'pass', 'fail', 'warn', or 'skip'.
    """
    table = Table(
        title=title,
        box=box.ROUNDED,
        show_header=True,
        header_style="bold",
        padding=(0, 1),
    )
    table.add_column("Check", style="white", min_width=30)
    table.add_column("Status", justify="center", min_width=6)
    table.add_column("Details", style="dim")

    status_map = {
        "pass": PASS,
        "fail": FAIL,
        "warn": WARN,
        "skip": SKIP,
        "info": INFO,
    }

    for name, status, detail in results:
        table.add_row(name, status_map.get(status, status), detail)

    console.print()
    console.print(table)
    console.print()


# ---------------------------------------------------------------------------
# Config review panel
# ---------------------------------------------------------------------------
def config_review(title: str, items: dict[str, str], mask_keys: set[str] | None = None):
    """Show a config review panel with key-value pairs. Masks secrets."""
    if mask_keys is None:
        mask_keys = set()

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="white")

    for key, value in items.items():
        display_val = value
        if key in mask_keys and value:
            if len(value) > 8:
                display_val = value[:4] + "*" * (len(value) - 8) + value[-4:]
            else:
                display_val = "****"
        table.add_row(key, display_val)

    console.print(Panel(table, title=f"[bold]{title}[/bold]", border_style="blue"))
    console.print()


# ---------------------------------------------------------------------------
# Prompt wrappers (InquirerPy)
# ---------------------------------------------------------------------------
def ask_text(message: str, default: str = "", validate=None, password: bool = False) -> str:
    """Prompt for text input."""
    kwargs = {
        "message": message,
        "default": default,
        "amark": ">>",
        "qmark": "?",
    }
    if validate:
        kwargs["validate"] = validate
    if password:
        return inquirer.secret(**kwargs).execute()
    return inquirer.text(**kwargs).execute()


def ask_confirm(message: str, default: bool = True) -> bool:
    """Prompt for yes/no confirmation."""
    return inquirer.confirm(
        message=message,
        default=default,
        amark=">>",
        qmark="?",
    ).execute()


def ask_select(message: str, choices: list[str | dict], default: str | None = None) -> str:
    """Prompt for single selection from a list."""
    kwargs = {
        "message": message,
        "choices": choices,
        "amark": ">>",
        "qmark": "?",
    }
    if default is not None:
        kwargs["default"] = default
    return inquirer.select(**kwargs).execute()


def ask_filepath(message: str, default: str = "") -> str:
    """Prompt for a file path with completion."""
    return inquirer.filepath(
        message=message,
        default=default,
        amark=">>",
        qmark="?",
    ).execute()


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------
def run_cmd(
    cmd: list[str] | str,
    capture: bool = True,
    check: bool = True,
    shell: bool = False,
    env: dict | None = None,
    cwd: str | None = None,
) -> subprocess.CompletedProcess:
    """Run a command with sensible defaults."""
    merged_env = None
    if env:
        merged_env = {**os.environ, **env}
    kwargs = {
        "capture_output": capture,
        "text": True,
        "check": check,
        "shell": shell,
        "env": merged_env,
    }
    if cwd:
        kwargs["cwd"] = cwd
    return subprocess.run(cmd, **kwargs)


def run_cmd_live(cmd: list[str] | str, shell: bool = False, cwd: str | None = None) -> int:
    """Run a command with live output. Returns exit code."""
    result = subprocess.run(
        cmd,
        shell=shell,
        cwd=cwd,
    )
    return result.returncode


def cmd_exists(name: str) -> bool:
    """Check if a command exists on PATH."""
    try:
        subprocess.run(
            ["which", name],
            capture_output=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_cmd_output(cmd: list[str] | str, shell: bool = False, default: str = "") -> str:
    """Get command stdout, returning default on failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            shell=shell,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return default


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------
def open_browser(url: str):
    """Try to open a URL in the user's browser."""
    import webbrowser
    try:
        webbrowser.open(url)
        info(f"Opened browser: {url}")
    except Exception:
        info(f"Please open this URL in your browser:\n    {url}")


def wait_for_enter(message: str = "Press Enter to continue..."):
    """Pause and wait for the user to press Enter."""
    console.input(f"  [dim]{message}[/dim]")
