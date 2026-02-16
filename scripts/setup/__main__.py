"""
Entry point for the setup wizard.

Usage:
    python -m scripts.setup             # Full wizard
    python -m scripts.setup verify      # Health checks only
    python -m scripts.setup --help      # Show help
"""
import sys


def main():
    args = sys.argv[1:]

    if "--help" in args or "-h" in args:
        print_help()
        sys.exit(0)

    if "verify" in args or "--verify" in args:
        from scripts.setup.wizard import run_verify_only
        run_verify_only()
    else:
        from scripts.setup.wizard import run_wizard
        run_wizard()


def print_help():
    help_text = """
Mail App Setup Wizard
=====================

Usage:
    python -m scripts.setup             Run the full interactive setup wizard
    python -m scripts.setup verify      Run health checks only
    python -m scripts.setup --help      Show this help message

The wizard guides you through:
    1. Pre-flight checks (OS, dependencies)
    2. System dependency installation
    3. Google Cloud & OAuth configuration
    4. Domain & SSL setup
    5. Database creation
    6. Application configuration (.env)
    7. Application build (venv, frontend, migrations)
    8. Service installation (systemd)
    9. Comprehensive verification

The wizard is idempotent and can be re-run safely. Progress is saved
so you can resume if interrupted.

Quick start:
    bash scripts/install.sh             Bootstrap + run wizard
    bash scripts/install.sh --verify    Bootstrap + health checks only
"""
    print(help_text)


if __name__ == "__main__":
    main()
