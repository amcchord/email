"""
Step 5: Database setup.

Creates PostgreSQL user and database, tests connectivity.
Generates a secure random password.
"""
import os
import secrets
import string

from scripts.setup import ui


def _sudo_cmd(cmd: list[str]) -> list[str]:
    """Prepend sudo if not running as root."""
    if os.geteuid() == 0:
        return cmd
    return ["sudo"] + cmd


def _pg_is_running() -> bool:
    """Check if PostgreSQL is accepting connections."""
    result = ui.run_cmd(["pg_isready", "-q"], capture=True, check=False)
    return result.returncode == 0


def _start_postgresql():
    """Try to start PostgreSQL."""
    ui.info("Starting PostgreSQL...")
    # Try systemctl first
    result = ui.run_cmd(
        _sudo_cmd(["systemctl", "start", "postgresql"]),
        capture=True,
        check=False,
    )
    if result.returncode == 0:
        return

    # Try pg_ctlcluster (Debian/Ubuntu)
    ui.run_cmd(
        _sudo_cmd(["pg_ctlcluster", "17", "main", "start"]),
        capture=True,
        check=False,
    )


def _run_psql(sql: str, db: str = "postgres") -> tuple[bool, str]:
    """Run a SQL command via psql as the postgres user. Returns (success, output)."""
    result = ui.run_cmd(
        _sudo_cmd(["su", "-", "postgres", "-c", f'psql -d {db} -tAc "{sql}"']),
        capture=True,
        check=False,
    )
    return result.returncode == 0, (result.stdout or "").strip()


def _user_exists(username: str) -> bool:
    """Check if a PostgreSQL role exists."""
    ok, output = _run_psql(f"SELECT 1 FROM pg_roles WHERE rolname='{username}'")
    return ok and output.strip() == "1"


def _database_exists(dbname: str) -> bool:
    """Check if a PostgreSQL database exists."""
    ok, output = _run_psql(f"SELECT 1 FROM pg_database WHERE datname='{dbname}'")
    return ok and output.strip() == "1"


def _generate_password(length: int = 24) -> str:
    """Generate a secure random password."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _test_connection(db_user: str, db_password: str, db_name: str, host: str, port: str) -> bool:
    """Test database connection using psql with password."""
    result = ui.run_cmd(
        ["psql", f"postgresql://{db_user}:{db_password}@{host}:{port}/{db_name}", "-c", "SELECT 1"],
        capture=True,
        check=False,
        env={"PGPASSWORD": db_password},
    )
    return result.returncode == 0


def run(state) -> str | None:
    """Run database setup."""
    ui.step_header(5, "Database Setup", "Create PostgreSQL user and database")

    # --- Ensure PostgreSQL is running ---
    if not _pg_is_running():
        _start_postgresql()
        if not _pg_is_running():
            ui.error("PostgreSQL is not running and could not be started.")
            ui.info("Start it manually and re-run setup.")
            raise RuntimeError("PostgreSQL not running")

    ui.success("PostgreSQL is running")

    # --- Configuration ---
    db_user = state.db_user
    db_name = state.db_name
    db_host = state.db_host
    db_port = state.db_port

    customize = ui.ask_confirm(
        f"Use default database settings? (user={db_user}, db={db_name}, host={db_host}:{db_port})",
        default=True,
    )

    if not customize:
        db_user = ui.ask_text("Database user:", default=db_user)
        db_name = ui.ask_text("Database name:", default=db_name)
        db_host = ui.ask_text("Database host:", default=db_host)
        db_port = ui.ask_text("Database port:", default=db_port)

    state.db_user = db_user
    state.db_name = db_name
    state.db_host = db_host
    state.db_port = db_port

    # --- Generate or ask for password ---
    generated_pw = _generate_password()
    use_generated = ui.ask_confirm(
        "Generate a secure random database password? (recommended)",
        default=True,
    )
    if use_generated:
        db_password = generated_pw
    else:
        db_password = ui.ask_text("Enter database password:", password=True)

    state.db_password = db_password

    # --- Create user ---
    if _user_exists(db_user):
        ui.success(f"PostgreSQL role '{db_user}' already exists")
        # Update password
        ui.info("Updating password for existing role...")
        ok, _ = _run_psql(f"ALTER ROLE {db_user} WITH PASSWORD '{db_password}'")
        if ok:
            ui.success("Password updated")
        else:
            ui.warning("Could not update password. You may need to do this manually.")
    else:
        ui.info(f"Creating PostgreSQL role '{db_user}'...")
        ok, output = _run_psql(f"CREATE ROLE {db_user} WITH LOGIN PASSWORD '{db_password}'")
        if ok:
            ui.success(f"Created role '{db_user}'")
        else:
            ui.error(f"Failed to create role: {output}")
            raise RuntimeError(f"Failed to create PostgreSQL role '{db_user}'")

    # --- Create database ---
    if _database_exists(db_name):
        ui.success(f"Database '{db_name}' already exists")
        # Ensure ownership
        _run_psql(f"ALTER DATABASE {db_name} OWNER TO {db_user}")
    else:
        ui.info(f"Creating database '{db_name}'...")
        ok, output = _run_psql(f"CREATE DATABASE {db_name} OWNER {db_user}")
        if ok:
            ui.success(f"Created database '{db_name}'")
        else:
            ui.error(f"Failed to create database: {output}")
            raise RuntimeError(f"Failed to create database '{db_name}'")

    # --- Grant privileges ---
    _run_psql(f"GRANT ALL PRIVILEGES ON DATABASE {db_name} TO {db_user}")

    # --- Test connection ---
    ui.info("Testing database connection...")
    if _test_connection(db_user, db_password, db_name, db_host, db_port):
        ui.success("Database connection successful!")
    else:
        ui.warning("Direct connection test failed (may need pg_hba.conf changes).")
        ui.info("The app will attempt to connect using the configured DATABASE_URL.")

        # Check if pg_hba.conf allows password auth
        ui.info("Checking pg_hba.conf for md5/scram-sha-256 authentication...")
        hba_paths = [
            "/etc/postgresql/17/main/pg_hba.conf",
            "/etc/postgresql/16/main/pg_hba.conf",
            "/etc/postgresql/15/main/pg_hba.conf",
            "/var/lib/pgsql/data/pg_hba.conf",
        ]
        hba_found = None
        for path in hba_paths:
            if os.path.exists(path):
                hba_found = path
                break

        if hba_found:
            ui.info(f"  pg_hba.conf: {hba_found}")
            ui.info("  If connection fails, ensure there's a line like:")
            ui.info(f"    local   {db_name}   {db_user}   md5")
            ui.info(f"    host    {db_name}   {db_user}   127.0.0.1/32   md5")

    ui.console.print()

    # Show summary
    ui.config_review("Database Configuration", {
        "User": db_user,
        "Database": db_name,
        "Host": f"{db_host}:{db_port}",
        "Password": db_password,
        "URL": state.database_url(),
    }, mask_keys={"Password"})

    return None
