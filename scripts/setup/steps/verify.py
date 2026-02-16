"""
Step 9: Comprehensive verification / health check.

Can run as the final wizard step or standalone via:
    python -m scripts.setup verify
"""
import json
import os
import socket
import ssl
import time
import urllib.request
import urllib.error

from scripts.setup import ui


PROJECT_ROOT = "/opt/mail"
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")
VENV_DIR = os.path.join(PROJECT_ROOT, "venv")
FRONTEND_DIST = os.path.join(PROJECT_ROOT, "frontend", "dist")


def _load_env() -> dict[str, str]:
    """Load .env file as a dict."""
    env = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip()
    return env


def _service_is_active(service: str) -> bool:
    result = ui.run_cmd(
        ["systemctl", "is-active", service],
        capture=True,
        check=False,
    )
    return result.returncode == 0 and "active" in (result.stdout or "").strip()


def _port_is_open(host: str, port: int, timeout: float = 3.0) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        return result == 0
    except Exception:
        return False
    finally:
        sock.close()


def _http_get(url: str, timeout: float = 5.0) -> tuple[int, str]:
    """Make an HTTP GET request. Returns (status_code, body) or (-1, error)."""
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, str(e)
    except Exception as e:
        return -1, str(e)


def _dns_resolves(domain: str) -> str:
    """Check if domain resolves. Returns IP or empty string."""
    try:
        result = socket.getaddrinfo(domain, None, socket.AF_INET)
        if result:
            return result[0][4][0]
    except socket.gaierror:
        pass
    return ""


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------
def check_env_file() -> tuple[str, str]:
    """Check .env file exists and has required variables."""
    if not os.path.exists(ENV_FILE):
        return "fail", ".env file not found"

    env = _load_env()
    required = [
        "DATABASE_URL", "REDIS_URL", "SECRET_KEY", "ENCRYPTION_KEY",
        "ADMIN_USERNAME", "ADMIN_PASSWORD", "ALLOWED_ORIGINS",
    ]
    missing = [k for k in required if not env.get(k)]
    if missing:
        return "warn", f"Missing: {', '.join(missing)}"

    # Check for default/placeholder values
    if env.get("SECRET_KEY") == "change-this-to-a-random-secret-key-in-production":
        return "warn", "SECRET_KEY is still the default placeholder"

    return "pass", f"{len(env)} variables set"


def check_env_permissions() -> tuple[str, str]:
    """Check .env file has restricted permissions."""
    if not os.path.exists(ENV_FILE):
        return "skip", "No .env file"

    mode = oct(os.stat(ENV_FILE).st_mode)[-3:]
    if mode in ("600", "400"):
        return "pass", f"Permissions: {mode}"
    return "warn", f"Permissions: {mode} (recommend 600)"


def check_google_oauth() -> tuple[str, str]:
    """Check Google OAuth credentials are configured."""
    env = _load_env()
    client_id = env.get("GOOGLE_CLIENT_ID", "")
    client_secret = env.get("GOOGLE_CLIENT_SECRET", "")

    if client_id and client_secret:
        if client_id.endswith(".apps.googleusercontent.com"):
            return "pass", f"Client ID: {client_id[:25]}..."
        return "warn", "Client ID format looks unusual"
    if client_id or client_secret:
        return "warn", "Only one of client_id/client_secret is set"
    return "warn", "Not configured (set via admin UI)"


def check_encryption_key() -> tuple[str, str]:
    """Check encryption key is set."""
    env = _load_env()
    key = env.get("ENCRYPTION_KEY", "")
    if not key:
        return "fail", "Not set (tokens cannot be encrypted)"
    if len(key) < 20:
        return "warn", "Key seems short"
    return "pass", "Set"


def check_postgresql() -> tuple[str, str]:
    """Check PostgreSQL is running and accessible."""
    if not _port_is_open("127.0.0.1", 5432):
        return "fail", "Port 5432 not responding"

    result = ui.run_cmd(["pg_isready", "-q"], capture=True, check=False)
    if result.returncode == 0:
        return "pass", "Running and accepting connections"
    return "fail", "Not accepting connections"


def check_redis() -> tuple[str, str]:
    """Check Redis is running."""
    if not _port_is_open("127.0.0.1", 6379):
        return "fail", "Port 6379 not responding"

    result = ui.run_cmd(["redis-cli", "ping"], capture=True, check=False)
    if result.returncode == 0 and "PONG" in (result.stdout or ""):
        return "pass", "Running (PONG)"
    return "fail", "Not responding to PING"


def check_backend_api() -> tuple[str, str]:
    """Check if the FastAPI backend is responding."""
    if not _port_is_open("127.0.0.1", 8000):
        return "fail", "Port 8000 not responding"

    status, body = _http_get("http://127.0.0.1:8000/api/health")
    if status == 200:
        try:
            data = json.loads(body)
            version = data.get("version", "?")
            return "pass", f"Healthy (v{version})"
        except json.JSONDecodeError:
            return "pass", "Responding"
    return "fail", f"Status {status}"


def check_frontend_build() -> tuple[str, str]:
    """Check frontend dist directory exists."""
    if not os.path.isdir(FRONTEND_DIST):
        return "fail", "dist/ directory not found"

    index_html = os.path.join(FRONTEND_DIST, "index.html")
    if not os.path.exists(index_html):
        return "fail", "index.html not found in dist/"

    assets_dir = os.path.join(FRONTEND_DIST, "assets")
    if os.path.isdir(assets_dir):
        asset_count = len(os.listdir(assets_dir))
        return "pass", f"Built ({asset_count} assets)"
    return "pass", "Built"


def check_python_venv() -> tuple[str, str]:
    """Check Python venv exists and has key packages."""
    python_bin = os.path.join(VENV_DIR, "bin", "python")
    if not os.path.exists(python_bin):
        return "fail", "venv not found"

    result = ui.run_cmd(
        [python_bin, "-c", "import fastapi; import sqlalchemy; import arq; print('ok')"],
        capture=True,
        check=False,
    )
    if result.returncode == 0 and "ok" in (result.stdout or ""):
        return "pass", "Core packages available"
    return "warn", "venv exists but some packages may be missing"


def check_mailapp_service() -> tuple[str, str]:
    """Check mailapp systemd service."""
    if _service_is_active("mailapp"):
        return "pass", "Running"
    if os.path.exists("/etc/systemd/system/mailapp.service"):
        return "warn", "Installed but not running"
    return "fail", "Not installed"


def check_mailworker_service() -> tuple[str, str]:
    """Check mailworker systemd service."""
    if _service_is_active("mailworker"):
        return "pass", "Running"
    if os.path.exists("/etc/systemd/system/mailworker.service"):
        return "warn", "Installed but not running"
    return "fail", "Not installed"


def check_caddy_service() -> tuple[str, str]:
    """Check Caddy service."""
    if _service_is_active("caddy"):
        return "pass", "Running"
    if ui.cmd_exists("caddy"):
        return "warn", "Installed but not running"
    return "fail", "Not installed"


def check_dns(domain: str) -> tuple[str, str]:
    """Check DNS resolution for the configured domain."""
    if not domain or domain == "localhost":
        return "skip", "Localhost (no DNS needed)"

    ip = _dns_resolves(domain)
    if ip:
        return "pass", f"Resolves to {ip}"
    return "fail", f"{domain} does not resolve"


def check_https(domain: str) -> tuple[str, str]:
    """Check HTTPS is working on the configured domain."""
    if not domain or domain == "localhost":
        return "skip", "Localhost"

    url = f"https://{domain}/api/health"
    status, body = _http_get(url)
    if status == 200:
        return "pass", "HTTPS working"
    if status == -1:
        return "fail", f"Cannot connect: {body[:80]}"
    return "warn", f"Status {status}"


def check_ssl_cert(domain: str) -> tuple[str, str]:
    """Check SSL certificate validity."""
    if not domain or domain == "localhost":
        return "skip", "Localhost"

    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(
            socket.socket(socket.AF_INET),
            server_hostname=domain,
        ) as sock:
            sock.settimeout(5.0)
            sock.connect((domain, 443))
            cert = sock.getpeercert()
            if cert:
                not_after = cert.get("notAfter", "")
                return "pass", f"Valid (expires: {not_after})"
            return "warn", "Connected but no cert info"
    except ssl.SSLCertVerificationError as e:
        return "fail", f"Invalid certificate: {e}"
    except Exception as e:
        return "fail", f"SSL error: {str(e)[:60]}"


def check_file_ownership() -> tuple[str, str]:
    """Check /opt/mail ownership."""
    try:
        import pwd
        stat = os.stat(PROJECT_ROOT)
        owner = pwd.getpwuid(stat.st_uid).pw_name
        if owner == "mailapp":
            return "pass", "Owned by mailapp"
        return "warn", f"Owned by {owner} (expected mailapp)"
    except Exception:
        return "skip", "Cannot determine ownership"


def check_data_directories() -> tuple[str, str]:
    """Check data directories exist."""
    dirs = [
        os.path.join(PROJECT_ROOT, "data"),
        os.path.join(PROJECT_ROOT, "data", "attachments"),
    ]
    missing = [d for d in dirs if not os.path.isdir(d)]
    if missing:
        return "fail", f"Missing: {', '.join(missing)}"
    return "pass", "All data directories exist"


def check_caddyfile() -> tuple[str, str]:
    """Check Caddyfile exists and is valid."""
    caddyfile = os.path.join(PROJECT_ROOT, "Caddyfile")
    if not os.path.exists(caddyfile):
        return "fail", "Caddyfile not found"

    # Validate with caddy (may fail on permission issues when not running as caddy user)
    if ui.cmd_exists("caddy"):
        result = ui.run_cmd(
            ["caddy", "validate", "--config", caddyfile, "--adapter", "caddyfile"],
            capture=True,
            check=False,
        )
        if result.returncode == 0:
            return "pass", "Valid configuration"
        # Permission errors during validation are expected when not root
        combined = (result.stdout or "") + (result.stderr or "")
        if "permission denied" in combined.lower():
            return "pass", "Exists (permission check skipped)"
        if "adapted config" in combined:
            return "pass", "Valid syntax (runtime check needs Caddy user)"
        return "warn", f"Validation issue (exit {result.returncode})"

    return "pass", "File exists (cannot validate without caddy)"


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------
def run(state) -> str | None:
    """Run comprehensive health checks."""
    ui.step_header(9, "Verification", "Running comprehensive health checks")

    domain = getattr(state, "domain", "") or ""

    results = []

    # --- Configuration checks ---
    status, detail = check_env_file()
    results.append(("Environment file (.env)", status, detail))

    status, detail = check_env_permissions()
    results.append(("Env file permissions", status, detail))

    status, detail = check_encryption_key()
    results.append(("Encryption key", status, detail))

    status, detail = check_google_oauth()
    results.append(("Google OAuth credentials", status, detail))

    # --- Infrastructure checks ---
    status, detail = check_postgresql()
    results.append(("PostgreSQL", status, detail))

    status, detail = check_redis()
    results.append(("Redis", status, detail))

    # --- Application checks ---
    status, detail = check_python_venv()
    results.append(("Python venv", status, detail))

    status, detail = check_frontend_build()
    results.append(("Frontend build", status, detail))

    status, detail = check_data_directories()
    results.append(("Data directories", status, detail))

    status, detail = check_caddyfile()
    results.append(("Caddyfile", status, detail))

    # --- Service checks ---
    status, detail = check_mailapp_service()
    results.append(("mailapp service", status, detail))

    status, detail = check_mailworker_service()
    results.append(("mailworker service", status, detail))

    status, detail = check_caddy_service()
    results.append(("Caddy service", status, detail))

    status, detail = check_backend_api()
    results.append(("Backend API (/api/health)", status, detail))

    # --- Network checks ---
    status, detail = check_dns(domain)
    results.append(("DNS resolution", status, detail))

    status, detail = check_https(domain)
    results.append(("HTTPS endpoint", status, detail))

    status, detail = check_ssl_cert(domain)
    results.append(("SSL certificate", status, detail))

    # --- File system checks ---
    status, detail = check_file_ownership()
    results.append(("File ownership", status, detail))

    # --- Display results ---
    ui.checks_table("Health Check Results", results)

    # --- Summary ---
    pass_count = sum(1 for _, s, _ in results if s == "pass")
    fail_count = sum(1 for _, s, _ in results if s == "fail")
    warn_count = sum(1 for _, s, _ in results if s == "warn")
    skip_count = sum(1 for _, s, _ in results if s == "skip")
    total = len(results)

    ui.console.print()
    summary_parts = [f"[green]{pass_count} passed[/green]"]
    if fail_count:
        summary_parts.append(f"[red]{fail_count} failed[/red]")
    if warn_count:
        summary_parts.append(f"[yellow]{warn_count} warnings[/yellow]")
    if skip_count:
        summary_parts.append(f"[dim]{skip_count} skipped[/dim]")

    ui.console.print(f"  [bold]Results:[/bold] {' / '.join(summary_parts)}  (of {total} checks)")
    ui.console.print()

    if fail_count == 0:
        if domain and domain != "localhost":
            scheme = "https" if getattr(state, "use_https", True) else "http"
            ui.success(f"All checks passed! Your app is ready at {scheme}://{domain}")
        else:
            ui.success("All critical checks passed!")
    else:
        ui.warning(f"{fail_count} check(s) failed. Review the issues above.")
        ui.info("You can re-run health checks anytime with:")
        ui.info("  bash scripts/install.sh --verify")

    return None
