"""
Step 4 (Domain) and Step 6 (Configuration).

Handles domain/SSL configuration, .env generation, Caddyfile
generation, and alembic.ini updates.
"""
import os
import secrets
import socket
import subprocess

from scripts.setup import ui


PROJECT_ROOT = "/opt/mail"
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")
CADDYFILE = os.path.join(PROJECT_ROOT, "Caddyfile")
ALEMBIC_INI = os.path.join(PROJECT_ROOT, "alembic.ini")


def _generate_secret_key(length: int = 48) -> str:
    """Generate a URL-safe secret key."""
    return secrets.token_urlsafe(length)


def _generate_fernet_key() -> str:
    """Generate a Fernet encryption key."""
    try:
        from cryptography.fernet import Fernet
        return Fernet.generate_key().decode()
    except ImportError:
        # If cryptography isn't installed yet, generate raw base64
        import base64
        key = secrets.token_bytes(32)
        return base64.urlsafe_b64encode(key).decode()


def _get_public_ip() -> str:
    """Try to detect the server's public IP."""
    for service in [
        "https://api.ipify.org",
        "https://icanhazip.com",
        "https://ifconfig.me/ip",
    ]:
        try:
            import urllib.request
            with urllib.request.urlopen(service, timeout=5) as resp:
                return resp.read().decode().strip()
        except Exception:
            continue
    return ""


def _check_dns(domain: str) -> str:
    """Resolve a domain and return the IP, or empty string."""
    try:
        result = socket.getaddrinfo(domain, None, socket.AF_INET)
        if result:
            return result[0][4][0]
    except socket.gaierror:
        pass
    return ""


def _sudo_cmd(cmd: list[str]) -> list[str]:
    if os.geteuid() == 0:
        return cmd
    return ["sudo"] + cmd


# ---------------------------------------------------------------------------
# Step 4: Domain & SSL
# ---------------------------------------------------------------------------
def run_domain(state) -> str | None:
    """Run domain and SSL configuration."""
    ui.step_header(4, "Domain & SSL", "Configure your domain name and HTTPS")

    # Ask for domain
    default_domain = state.domain if state.domain else ""
    domain = ui.ask_text(
        "Enter your domain name (e.g., email.example.com):",
        default=default_domain,
        validate=lambda val: bool(val.strip()) or "Domain name is required",
    )
    state.domain = domain.strip()

    # HTTPS
    if domain == "localhost":
        state.use_https = False
        ui.info("Using HTTP for localhost (no TLS)")
    else:
        state.use_https = ui.ask_confirm(
            "Use HTTPS with automatic TLS via Caddy? (recommended for production)",
            default=True,
        )

    scheme = "https" if state.use_https else "http"
    ui.success(f"URL: {scheme}://{state.domain}")
    ui.console.print()

    # DNS check
    if state.domain != "localhost":
        ui.info("Checking DNS resolution...")
        resolved_ip = _check_dns(state.domain)
        public_ip = _get_public_ip()

        if resolved_ip:
            ui.success(f"  {state.domain} resolves to {resolved_ip}")
            if public_ip:
                if resolved_ip == public_ip:
                    ui.success(f"  Matches this server's public IP ({public_ip})")
                else:
                    ui.warning(f"  This server's public IP is {public_ip}")
                    ui.warning(f"  DNS points to {resolved_ip} — make sure this is correct")
        else:
            ui.warning(f"  {state.domain} does not resolve yet")
            if public_ip:
                ui.info(f"  Set a DNS A record pointing to: {public_ip}")
            else:
                ui.info("  Set a DNS A record pointing to this server's IP address")
            ui.info("  Caddy will auto-obtain a TLS certificate once DNS is configured")

    # Generate Caddyfile
    ui.console.print()
    ui.info("Generating Caddyfile...")

    caddyfile_content = _generate_caddyfile(state.domain, state.use_https)

    # Show preview
    ui.console.print(
        ui.Panel(
            caddyfile_content,
            title="[bold]Caddyfile[/bold]",
            border_style="blue",
        )
    )

    write_it = True
    if os.path.exists(CADDYFILE):
        write_it = ui.ask_confirm(
            "Caddyfile already exists. Overwrite?",
            default=True,
        )

    if write_it:
        with open(CADDYFILE, "w") as f:
            f.write(caddyfile_content)
        ui.success(f"Wrote {CADDYFILE}")
    else:
        ui.info("Keeping existing Caddyfile")

    return None


def _generate_caddyfile(domain: str, use_https: bool) -> str:
    """Generate Caddyfile content."""
    if domain == "localhost" or not use_https:
        address_block = f":{80}"
        if domain != "localhost":
            address_block = f"http://{domain}"
    else:
        address_block = domain

    return f"""{address_block} {{
    # Security headers
    header {{
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        X-XSS-Protection "1; mode=block"
        Referrer-Policy "strict-origin-when-cross-origin"
        Permissions-Policy "camera=(), microphone=(), geolocation=()"
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        -Server
    }}

    # API proxy to FastAPI
    handle /api/* {{
        reverse_proxy localhost:8000
    }}

    # Serve frontend static files
    handle {{
        root * /opt/mail/frontend/dist
        try_files {{path}} /index.html
        file_server
    }}

    # Logging
    log {{
        output file /var/log/caddy/mail.log
        format console
    }}
}}
"""


# ---------------------------------------------------------------------------
# Step 6: Application Configuration
# ---------------------------------------------------------------------------
def run_config(state) -> str | None:
    """Run application configuration — generate .env and update alembic.ini."""
    ui.step_header(6, "Application Configuration", "Generate .env file and configure settings")

    # --- Collect all configuration ---
    scheme = "https" if state.use_https else "http"
    origin = f"{scheme}://{state.domain}"

    # Secret key
    if not state.secret_key:
        state.secret_key = _generate_secret_key()
    ui.success("Generated SECRET_KEY")

    # Encryption key
    if not state.encryption_key:
        state.encryption_key = _generate_fernet_key()
    ui.success("Generated ENCRYPTION_KEY")

    # Admin credentials
    ui.console.print()
    ui.info("[bold]Admin Account[/bold]")
    state.admin_username = ui.ask_text(
        "Admin username:",
        default=state.admin_username,
    )
    state.admin_password = ui.ask_text(
        "Admin password:",
        default="",
        password=True,
        validate=lambda val: len(val) >= 8 or "Password must be at least 8 characters",
    )

    # Claude API key (optional)
    ui.console.print()
    ui.info("[bold]AI Configuration (optional)[/bold]")
    ui.info("The Claude API key enables AI features like email categorization and summarization.")
    ui.info("You can also set this later in the admin panel.")
    set_claude = ui.ask_confirm("Set Claude API key now?", default=False)
    if set_claude:
        state.claude_api_key = ui.ask_text("Anthropic Claude API key:", password=True)

    # Redis URL
    ui.console.print()
    use_default_redis = ui.ask_confirm(
        f"Use default Redis URL? ({state.redis_url})",
        default=True,
    )
    if not use_default_redis:
        state.redis_url = ui.ask_text("Redis URL:", default=state.redis_url)

    # Google redirect URI
    redirect_uri = f"{origin}/api/auth/google/callback"

    # --- Build config dict ---
    config = {
        "DATABASE_URL": state.database_url(),
        "REDIS_URL": state.redis_url,
        "SECRET_KEY": state.secret_key,
        "ENCRYPTION_KEY": state.encryption_key,
        "ADMIN_USERNAME": state.admin_username,
        "ADMIN_PASSWORD": state.admin_password,
        "CLAUDE_API_KEY": state.claude_api_key,
        "GOOGLE_CLIENT_ID": state.google_client_id,
        "GOOGLE_CLIENT_SECRET": state.google_client_secret,
        "GOOGLE_REDIRECT_URI": redirect_uri,
        "ALLOWED_ORIGINS": origin,
    }

    # --- Review before writing ---
    ui.config_review(
        "Environment Configuration",
        config,
        mask_keys={"SECRET_KEY", "ENCRYPTION_KEY", "ADMIN_PASSWORD", "CLAUDE_API_KEY", "GOOGLE_CLIENT_SECRET", "DATABASE_URL"},
    )

    write_env = True
    if os.path.exists(ENV_FILE):
        write_env = ui.ask_confirm(".env file already exists. Overwrite?", default=True)

    if write_env:
        # Write .env file
        env_lines = []
        for key, value in config.items():
            env_lines.append(f"{key}={value}")
        env_content = "\n".join(env_lines) + "\n"

        with open(ENV_FILE, "w") as f:
            f.write(env_content)
        # Restrict permissions
        os.chmod(ENV_FILE, 0o600)
        ui.success(f"Wrote {ENV_FILE} (permissions: 600)")
    else:
        ui.info("Keeping existing .env file")

    # --- Update alembic.ini ---
    ui.console.print()
    ui.info("Updating alembic.ini with database URL...")

    if os.path.exists(ALEMBIC_INI):
        with open(ALEMBIC_INI) as f:
            content = f.read()

        # Replace the sqlalchemy.url line
        import re
        new_content = re.sub(
            r'^sqlalchemy\.url\s*=.*$',
            f'sqlalchemy.url = {state.database_url()}',
            content,
            flags=re.MULTILINE,
        )

        if new_content != content:
            with open(ALEMBIC_INI, "w") as f:
                f.write(new_content)
            ui.success("Updated alembic.ini")
        else:
            ui.info("alembic.ini already up to date")
    else:
        ui.warning(f"alembic.ini not found at {ALEMBIC_INI}")

    return None
