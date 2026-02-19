"""
Step 7: Application build.

Creates Python venv, installs dependencies, builds frontend,
runs database migrations, and sets up data directories.
"""
import os
import pwd

from rich.progress import Progress, SpinnerColumn, TextColumn

from scripts.setup import ui


PROJECT_ROOT = "/opt/mail"
VENV_DIR = os.path.join(PROJECT_ROOT, "venv")
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
ATTACHMENTS_DIR = os.path.join(DATA_DIR, "attachments")


def _sudo_cmd(cmd: list[str]) -> list[str]:
    if os.geteuid() == 0:
        return cmd
    return ["sudo"] + cmd


def _user_exists(username: str) -> bool:
    try:
        pwd.getpwnam(username)
        return True
    except KeyError:
        return False


def create_venv() -> bool:
    """Create Python virtual environment if it doesn't exist."""
    if os.path.exists(os.path.join(VENV_DIR, "bin", "python")):
        ui.success("Python venv already exists")
        return True

    ui.info("Creating Python virtual environment...")
    result = ui.run_cmd(
        ["python3", "-m", "venv", VENV_DIR],
        capture=True,
        check=False,
    )
    if result.returncode != 0:
        ui.error(f"Failed to create venv: {result.stderr}")
        return False

    ui.success(f"Created venv at {VENV_DIR}")
    return True


def install_python_deps() -> bool:
    """Install Python dependencies from requirements.txt."""
    pip = os.path.join(VENV_DIR, "bin", "pip")
    requirements = os.path.join(PROJECT_ROOT, "requirements.txt")

    if not os.path.exists(requirements):
        ui.error(f"requirements.txt not found at {requirements}")
        return False

    ui.info("Upgrading pip...")
    ui.run_cmd([pip, "install", "--quiet", "--upgrade", "pip"], capture=True, check=False)

    ui.info("Installing Python dependencies (this may take a minute)...")
    result = ui.run_cmd(
        [pip, "install", "--quiet", "-r", requirements],
        capture=True,
        check=False,
    )
    if result.returncode != 0:
        ui.error(f"pip install failed: {result.stderr}")
        # Show last few lines of error output
        if result.stderr:
            for line in result.stderr.strip().split("\n")[-5:]:
                ui.error(f"  {line}")
        return False

    ui.success("Python dependencies installed")
    return True


def install_playwright_browsers() -> bool:
    """Install Playwright Chromium browser for AI-powered unsubscribe."""
    playwright_bin = os.path.join(VENV_DIR, "bin", "playwright")
    if not os.path.exists(playwright_bin):
        ui.warning("Playwright not found in venv, skipping browser install")
        return True

    ui.info("Installing Playwright Chromium browser (this may take a minute)...")
    result = ui.run_cmd(
        _sudo_cmd([playwright_bin, "install", "chromium", "--with-deps"]),
        capture=True,
        check=False,
    )
    if result.returncode != 0:
        ui.warning("Playwright browser install failed (non-fatal, unsubscribe automation will not work)")
        if result.stderr:
            for line in result.stderr.strip().split("\n")[-5:]:
                ui.warning(f"  {line}")
        return False

    ui.success("Playwright Chromium browser installed")
    return True


def install_frontend_deps() -> bool:
    """Install frontend npm dependencies."""
    if not os.path.exists(os.path.join(FRONTEND_DIR, "package.json")):
        ui.error(f"package.json not found in {FRONTEND_DIR}")
        return False

    ui.info("Installing frontend dependencies...")
    result = ui.run_cmd(
        ["npm", "install"],
        capture=True,
        check=False,
        cwd=FRONTEND_DIR,
    )
    if result.returncode != 0:
        ui.error(f"npm install failed: {result.stderr}")
        return False

    ui.success("Frontend dependencies installed")
    return True


def build_frontend() -> bool:
    """Build the frontend."""
    ui.info("Building frontend (Svelte + Vite)...")
    result = ui.run_cmd(
        ["npm", "run", "build"],
        capture=True,
        check=False,
        cwd=FRONTEND_DIR,
    )
    if result.returncode != 0:
        ui.error(f"Frontend build failed: {result.stderr}")
        if result.stdout:
            for line in result.stdout.strip().split("\n")[-5:]:
                ui.error(f"  {line}")
        return False

    dist_dir = os.path.join(FRONTEND_DIR, "dist")
    if os.path.isdir(dist_dir):
        ui.success(f"Frontend built: {dist_dir}")
        return True
    else:
        ui.error("Build completed but dist directory not found")
        return False


def run_migrations() -> bool:
    """Run Alembic database migrations."""
    alembic_bin = os.path.join(VENV_DIR, "bin", "alembic")
    if not os.path.exists(alembic_bin):
        # Try using python -m alembic
        alembic_bin = None

    ui.info("Running database migrations...")

    if alembic_bin:
        cmd = [alembic_bin, "upgrade", "head"]
    else:
        python_bin = os.path.join(VENV_DIR, "bin", "python")
        cmd = [python_bin, "-m", "alembic", "upgrade", "head"]

    result = ui.run_cmd(
        cmd,
        capture=True,
        check=False,
        cwd=PROJECT_ROOT,
    )

    if result.returncode != 0:
        ui.error(f"Migrations failed: {result.stderr}")
        if result.stdout:
            for line in result.stdout.strip().split("\n")[-5:]:
                ui.error(f"  {line}")
        return False

    ui.success("Database migrations applied")
    return True


def setup_directories() -> bool:
    """Create data directories with correct ownership."""
    dirs = [DATA_DIR, ATTACHMENTS_DIR]

    for d in dirs:
        os.makedirs(d, exist_ok=True)

    # Create log directory
    log_dir = "/var/log/caddy"
    if not os.path.exists(log_dir):
        ui.run_cmd(_sudo_cmd(["mkdir", "-p", log_dir]), capture=True, check=False)

    # Write initial build version
    build_version_file = os.path.join(PROJECT_ROOT, ".build_version")
    import time
    with open(build_version_file, "w") as f:
        f.write(str(int(time.time())))

    ui.success("Data directories created")
    return True


def fix_ownership() -> bool:
    """Set correct file ownership for the mailapp user."""
    if not _user_exists("mailapp"):
        ui.info("User 'mailapp' doesn't exist, skipping ownership fix")
        return True

    ui.info("Setting file ownership...")
    result = ui.run_cmd(
        _sudo_cmd(["chown", "-R", "mailapp:mailapp", PROJECT_ROOT]),
        capture=True,
        check=False,
    )
    if result.returncode != 0:
        ui.warning("Could not set ownership (non-fatal)")
        return True

    # Make .env readable only by owner
    env_file = os.path.join(PROJECT_ROOT, ".env")
    if os.path.exists(env_file):
        ui.run_cmd(
            _sudo_cmd(["chmod", "600", env_file]),
            capture=True,
            check=False,
        )

    ui.success("File ownership set to mailapp:mailapp")
    return True


# ---------------------------------------------------------------------------
# Main step runner
# ---------------------------------------------------------------------------
def run(state) -> str | None:
    """Run application build step."""
    ui.step_header(
        7,
        "Build Application",
        "Create venv, install deps, build frontend, run migrations",
    )

    results = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=ui.console,
    ) as progress:
        task = progress.add_task("Building application...", total=8)

        # 1. Create venv
        progress.update(task, description="[cyan]Creating Python venv...")
        ok = create_venv()
        results.append(("Python venv", "pass" if ok else "fail", ""))
        progress.advance(task)

        # 2. Install Python deps
        progress.update(task, description="[cyan]Installing Python dependencies...")
        ok = install_python_deps()
        results.append(("Python dependencies", "pass" if ok else "fail", ""))
        progress.advance(task)

        # 3. Install Playwright browsers
        progress.update(task, description="[cyan]Installing Playwright browsers...")
        ok = install_playwright_browsers()
        results.append(("Playwright browsers", "pass" if ok else "warn", ""))
        progress.advance(task)

        # 4. Install frontend deps
        progress.update(task, description="[cyan]Installing frontend dependencies...")
        ok = install_frontend_deps()
        results.append(("Frontend dependencies", "pass" if ok else "fail", ""))
        progress.advance(task)

        # 5. Build frontend
        progress.update(task, description="[cyan]Building frontend...")
        ok = build_frontend()
        results.append(("Frontend build", "pass" if ok else "fail", ""))
        progress.advance(task)

        # 6. Database migrations
        progress.update(task, description="[cyan]Running database migrations...")
        ok = run_migrations()
        results.append(("Database migrations", "pass" if ok else "fail", ""))
        progress.advance(task)

        # 7. Data directories
        progress.update(task, description="[cyan]Setting up directories...")
        ok = setup_directories()
        results.append(("Data directories", "pass" if ok else "fail", ""))
        progress.advance(task)

        # 8. Fix ownership
        progress.update(task, description="[cyan]Setting file ownership...")
        ok = fix_ownership()
        results.append(("File ownership", "pass" if ok else "warn", ""))
        progress.advance(task)

    ui.console.print()
    ui.checks_table("Build Results", results)

    # Check for failures
    failures = [name for name, status, _ in results if status == "fail"]
    if failures:
        ui.warning(f"Some build steps failed: {', '.join(failures)}")
        ui.info("You may need to fix these issues before the app will work.")

    return None
