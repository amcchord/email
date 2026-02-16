"""
Step 3: Google Cloud & OAuth setup.

Automates as much as possible via gcloud CLI:
  - Install gcloud if needed
  - Authenticate
  - Create or select a GCP project
  - Enable Gmail, Calendar, People APIs
  - Guide OAuth consent screen setup
  - Collect and validate OAuth client credentials
"""
import os
import re
import json
import time

from scripts.setup import ui


# APIs that need to be enabled
REQUIRED_APIS = [
    "gmail.googleapis.com",
    "calendar-json.googleapis.com",
    "people.googleapis.com",
]

# Scopes the app uses (for consent screen guidance)
OAUTH_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/calendar.readonly",
]


# ---------------------------------------------------------------------------
# gcloud CLI helpers
# ---------------------------------------------------------------------------
def _gcloud_installed() -> bool:
    return ui.cmd_exists("gcloud")


def _gcloud_authenticated() -> bool:
    """Check if gcloud has an active account."""
    account = ui.get_cmd_output(["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"])
    return bool(account)


def _gcloud_project_exists(project_id: str) -> bool:
    """Check if a GCP project exists and is accessible."""
    result = ui.run_cmd(
        ["gcloud", "projects", "describe", project_id, "--format=value(projectId)"],
        capture=True,
        check=False,
    )
    return result.returncode == 0


def _gcloud_list_projects() -> list[str]:
    """List accessible GCP projects."""
    output = ui.get_cmd_output([
        "gcloud", "projects", "list", "--format=value(projectId)", "--limit=20",
    ])
    if output:
        return [p.strip() for p in output.strip().split("\n") if p.strip()]
    return []


def _gcloud_enabled_apis(project_id: str) -> list[str]:
    """List enabled APIs for a project."""
    output = ui.get_cmd_output([
        "gcloud", "services", "list",
        "--enabled",
        "--project", project_id,
        "--format=value(config.name)",
    ])
    if output:
        return [a.strip() for a in output.strip().split("\n") if a.strip()]
    return []


# ---------------------------------------------------------------------------
# Sub-steps
# ---------------------------------------------------------------------------
def setup_gcloud_cli(state) -> bool:
    """Ensure gcloud CLI is installed and authenticated."""
    ui.console.print()
    ui.info("[bold]Step 3a: gcloud CLI[/bold]")
    ui.console.print()

    if _gcloud_installed():
        ui.success("gcloud CLI is installed")
    else:
        ui.info("gcloud CLI is not installed.")
        install = ui.ask_confirm("Install gcloud CLI now?", default=True)
        if not install:
            ui.warning("gcloud CLI is needed for automated setup. You can install it later.")
            ui.info("Install guide: https://cloud.google.com/sdk/docs/install")
            return False

        ui.info("Installing gcloud CLI...")
        pkg_manager = state.pkg_manager

        if pkg_manager == "apt":
            cmds = [
                "curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg 2>/dev/null || true",
                'echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list >/dev/null',
                "sudo apt-get update -qq",
                "sudo apt-get install -y -qq google-cloud-cli",
            ]
            for cmd in cmds:
                result = ui.run_cmd(cmd, shell=True, capture=True, check=False)
                if result.returncode != 0:
                    ui.error("Failed to install gcloud via apt.")
                    break
        elif pkg_manager == "dnf":
            cmds = [
                'sudo tee /etc/yum.repos.d/google-cloud-sdk.repo << "EOF"\n[google-cloud-cli]\nname=Google Cloud CLI\nbaseurl=https://packages.cloud.google.com/yum/repos/cloud-sdk-el9-x86_64\nenabled=1\ngpgcheck=1\nrepo_gpgcheck=0\ngpgkey=https://packages.cloud.google.com/yum/doc/rpm-package-key.gpg\nEOF',
                "sudo dnf install -y -q google-cloud-cli",
            ]
            for cmd in cmds:
                ui.run_cmd(cmd, shell=True, capture=True, check=False)
        else:
            # Universal install script
            ui.info("Using the official install script...")
            ui.run_cmd(
                "curl -sSL https://sdk.cloud.google.com | bash -s -- --disable-prompts --install-dir=/opt",
                shell=True,
                capture=True,
                check=False,
            )
            # Add to PATH for this session
            sdk_path = "/opt/google-cloud-sdk/bin"
            if os.path.isdir(sdk_path):
                os.environ["PATH"] = sdk_path + ":" + os.environ.get("PATH", "")

        if not _gcloud_installed():
            ui.error("gcloud CLI installation failed.")
            ui.info("Install manually: https://cloud.google.com/sdk/docs/install")
            return False
        ui.success("gcloud CLI installed")

    # --- Authenticate ---
    if _gcloud_authenticated():
        account = ui.get_cmd_output([
            "gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)",
        ])
        ui.success(f"Authenticated as: {account}")
    else:
        ui.info("You need to authenticate with Google Cloud.")
        ui.info("A browser window will open for you to sign in.")
        ui.console.print()
        ui.wait_for_enter("Press Enter to open the Google sign-in page...")
        exit_code = ui.run_cmd_live(["gcloud", "auth", "login"])
        if exit_code != 0:
            ui.error("Authentication failed.")
            return False
        ui.success("Authenticated with Google Cloud")

    return True


def setup_project(state) -> bool:
    """Create or select a GCP project."""
    ui.console.print()
    ui.info("[bold]Step 3b: Google Cloud Project[/bold]")
    ui.console.print()

    existing_projects = _gcloud_list_projects()

    if existing_projects:
        choices = [
            {"name": "Use an existing project", "value": "existing"},
            {"name": "Create a new project", "value": "new"},
        ]
        action = ui.ask_select("Would you like to use an existing project or create a new one?", choices=choices)
    else:
        action = "new"

    if action == "existing":
        project_choices = [{"name": p, "value": p} for p in existing_projects]
        project_choices.append({"name": "Enter a project ID manually", "value": "_manual"})
        selected = ui.ask_select("Select a project:", choices=project_choices)

        if selected == "_manual":
            selected = ui.ask_text("Enter project ID:")

        state.gcloud_project_id = selected
    else:
        suggested_id = "mail-app-" + str(int(time.time()))[-6:]
        project_id = ui.ask_text(
            "Enter a project ID (lowercase, hyphens ok):",
            default=suggested_id,
            validate=lambda val: bool(re.match(r'^[a-z][a-z0-9\-]{4,28}[a-z0-9]$', val)) or "Invalid project ID (6-30 chars, lowercase + hyphens)",
        )

        ui.info(f"Creating project '{project_id}'...")
        result = ui.run_cmd(
            ["gcloud", "projects", "create", project_id, "--name=Mail App"],
            capture=True,
            check=False,
        )
        if result.returncode != 0:
            if "already exists" in (result.stderr or ""):
                ui.warning(f"Project '{project_id}' already exists, using it.")
            else:
                ui.error(f"Failed to create project: {result.stderr}")
                ui.info("You may need to create the project manually in the Google Cloud Console.")
                project_id = ui.ask_text("Enter the project ID you created:")
        else:
            ui.success(f"Created project: {project_id}")

        state.gcloud_project_id = project_id

    # Set as active project
    ui.run_cmd(
        ["gcloud", "config", "set", "project", state.gcloud_project_id],
        capture=True,
        check=False,
    )
    ui.success(f"Active project: {state.gcloud_project_id}")
    return True


def enable_apis(state) -> bool:
    """Enable required Google APIs."""
    ui.console.print()
    ui.info("[bold]Step 3c: Enable APIs[/bold]")
    ui.console.print()

    project_id = state.gcloud_project_id
    if not project_id:
        ui.error("No project ID set.")
        return False

    enabled = _gcloud_enabled_apis(project_id)
    to_enable = [api for api in REQUIRED_APIS if api not in enabled]

    if not to_enable:
        ui.success("All required APIs are already enabled")
        return True

    ui.info(f"Enabling {len(to_enable)} API(s)...")
    for api in to_enable:
        ui.info(f"  Enabling {api}...")
        result = ui.run_cmd(
            ["gcloud", "services", "enable", api, "--project", project_id],
            capture=True,
            check=False,
        )
        if result.returncode == 0:
            ui.success(f"  Enabled {api}")
        else:
            ui.error(f"  Failed to enable {api}: {result.stderr}")
            ui.info("  You may need to enable billing on the project first.")
            ui.info(f"  Go to: https://console.cloud.google.com/billing?project={project_id}")
            return False

    # Verify
    enabled = _gcloud_enabled_apis(project_id)
    all_good = all(api in enabled for api in REQUIRED_APIS)
    if all_good:
        ui.success("All required APIs are enabled")
    else:
        missing = [api for api in REQUIRED_APIS if api not in enabled]
        ui.warning(f"Some APIs still not enabled: {', '.join(missing)}")

    return all_good


def setup_oauth_consent(state) -> bool:
    """Guide user through OAuth consent screen setup."""
    ui.console.print()
    ui.info("[bold]Step 3d: OAuth Consent Screen[/bold]")
    ui.console.print()

    project_id = state.gcloud_project_id

    # Try to check if consent screen exists via gcloud
    brand_check = ui.run_cmd(
        ["gcloud", "alpha", "iap", "oauth-brands", "list", "--project", project_id, "--format=json"],
        capture=True,
        check=False,
    )

    has_brand = False
    if brand_check.returncode == 0 and brand_check.stdout:
        try:
            brands = json.loads(brand_check.stdout)
            if brands:
                has_brand = True
                ui.success("OAuth consent screen already configured")
        except json.JSONDecodeError:
            pass

    if not has_brand:
        ui.info("The OAuth consent screen needs to be configured.")
        ui.info("This tells users what your app does when they sign in with Google.")
        ui.console.print()

        # Try automated creation first
        ui.info("Attempting automated consent screen creation...")
        support_email = ui.get_cmd_output([
            "gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)",
        ])
        if not support_email:
            support_email = ui.ask_text("Enter your support email address:")

        result = ui.run_cmd(
            [
                "gcloud", "alpha", "iap", "oauth-brands", "create",
                "--application_title=Mail App",
                f"--support_email={support_email}",
                "--project", project_id,
            ],
            capture=True,
            check=False,
        )

        if result.returncode == 0:
            ui.success("OAuth consent screen created automatically!")
            has_brand = True
        else:
            ui.info("Automated setup didn't work (this is normal for most projects).")
            ui.info("You'll need to configure the consent screen manually.")
            ui.console.print()

            consent_url = f"https://console.cloud.google.com/apis/credentials/consent?project={project_id}"

            ui.console.print(
                ui.Panel(
                    f"[bold]Configure the OAuth Consent Screen:[/bold]\n\n"
                    f"1. Open this URL:\n"
                    f"   [cyan]{consent_url}[/cyan]\n\n"
                    f'2. Select [bold]"External"[/bold] user type, click Create\n\n'
                    f"3. Fill in:\n"
                    f'   - App name: [cyan]Mail App[/cyan]\n'
                    f"   - User support email: [cyan]{support_email}[/cyan]\n"
                    f"   - Developer contact email: [cyan]{support_email}[/cyan]\n\n"
                    f'4. Click [bold]"Save and Continue"[/bold] through Scopes\n'
                    f"   (scopes will be requested at runtime)\n\n"
                    f'5. Under Test Users, add your Gmail address\n\n'
                    f'6. Click [bold]"Save and Continue"[/bold] to finish',
                    title="[bold yellow]Manual Step Required[/bold yellow]",
                    border_style="yellow",
                    padding=(1, 2),
                )
            )
            ui.console.print()

            open_it = ui.ask_confirm("Open this URL in your browser?", default=True)
            if open_it:
                ui.open_browser(consent_url)

            ui.wait_for_enter("Press Enter once you've configured the consent screen...")
            has_brand = True

    return has_brand


def setup_oauth_credentials(state) -> bool:
    """Guide user through OAuth client credential creation and collect them."""
    ui.console.print()
    ui.info("[bold]Step 3e: OAuth Client Credentials[/bold]")
    ui.console.print()

    project_id = state.gcloud_project_id
    domain = state.domain if state.domain else "your-domain.com"
    scheme = "https" if state.use_https else "http"

    redirect_uri_login = f"{scheme}://{domain}/api/auth/google/callback"
    redirect_uri_connect = f"{scheme}://{domain}/api/accounts/oauth/callback"

    creds_url = f"https://console.cloud.google.com/apis/credentials/oauthclient?project={project_id}"

    ui.console.print(
        ui.Panel(
            f"[bold]Create OAuth Client Credentials:[/bold]\n\n"
            f"1. Open this URL:\n"
            f"   [cyan]{creds_url}[/cyan]\n\n"
            f'2. Application type: [bold]Web application[/bold]\n\n'
            f'3. Name: [cyan]Mail App[/cyan]\n\n'
            f"4. Under [bold]Authorized redirect URIs[/bold], add BOTH:\n"
            f"   [cyan]{redirect_uri_login}[/cyan]\n"
            f"   [cyan]{redirect_uri_connect}[/cyan]\n\n"
            f'5. Click [bold]Create[/bold]\n\n'
            f"6. Copy the [bold]Client ID[/bold] and [bold]Client Secret[/bold]",
            title="[bold yellow]Manual Step Required[/bold yellow]",
            border_style="yellow",
            padding=(1, 2),
        )
    )
    ui.console.print()

    open_it = ui.ask_confirm("Open this URL in your browser?", default=True)
    if open_it:
        ui.open_browser(creds_url)

    ui.console.print()
    ui.info("After creating the OAuth client, paste the credentials below.")
    ui.console.print()

    # Collect Client ID
    while True:
        client_id = ui.ask_text("Google Client ID:")
        if client_id.endswith(".apps.googleusercontent.com"):
            break
        ui.warning("Client ID should end with '.apps.googleusercontent.com'")
        retry = ui.ask_confirm("Try again?", default=True)
        if not retry:
            break

    # Collect Client Secret
    client_secret = ui.ask_text("Google Client Secret:", password=True)

    if not client_id or not client_secret:
        ui.warning("OAuth credentials not set. You can configure them later in the admin UI.")
        return True

    state.google_client_id = client_id
    state.google_client_secret = client_secret

    # Validate the credentials by checking the token endpoint
    ui.info("Validating credentials...")
    # We can't fully validate without an auth flow, but we can check the discovery doc
    try:
        import urllib.request
        discovery_url = "https://accounts.google.com/.well-known/openid-configuration"
        req = urllib.request.Request(discovery_url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if "authorization_endpoint" in data:
                ui.success("Google OAuth endpoints are reachable")
            else:
                ui.warning("Unexpected response from Google discovery endpoint")
    except Exception as exc:
        ui.warning(f"Could not reach Google OAuth endpoints: {exc}")

    ui.success(f"Client ID: {client_id[:20]}...")
    ui.success("Client Secret: ****")

    return True


def verify_google_setup(state) -> bool:
    """Verify that all Google Cloud setup is complete."""
    ui.console.print()
    ui.info("[bold]Step 3f: Verification[/bold]")
    ui.console.print()

    results = []

    # Check project
    if state.gcloud_project_id:
        if _gcloud_installed() and _gcloud_project_exists(state.gcloud_project_id):
            results.append(("GCP Project", "pass", state.gcloud_project_id))
        else:
            results.append(("GCP Project", "warn", f"{state.gcloud_project_id} (cannot verify)"))
    else:
        results.append(("GCP Project", "skip", "Not configured"))

    # Check APIs
    if state.gcloud_project_id and _gcloud_installed():
        enabled = _gcloud_enabled_apis(state.gcloud_project_id)
        for api in REQUIRED_APIS:
            if api in enabled:
                results.append((f"API: {api}", "pass", "Enabled"))
            else:
                results.append((f"API: {api}", "fail", "Not enabled"))
    else:
        for api in REQUIRED_APIS:
            results.append((f"API: {api}", "skip", "Cannot verify without gcloud"))

    # Check OAuth credentials
    if state.google_client_id:
        results.append(("OAuth Client ID", "pass", f"{state.google_client_id[:25]}..."))
    else:
        results.append(("OAuth Client ID", "warn", "Not set (can be added later)"))

    if state.google_client_secret:
        results.append(("OAuth Client Secret", "pass", "Set"))
    else:
        results.append(("OAuth Client Secret", "warn", "Not set (can be added later)"))

    ui.checks_table("Google Cloud Setup", results)
    return True


# ---------------------------------------------------------------------------
# Main step runner
# ---------------------------------------------------------------------------
def run(state) -> str | None:
    """Run the Google Cloud & OAuth setup step."""
    ui.step_header(
        3,
        "Google Cloud & OAuth",
        "Set up Google Cloud project, enable APIs, and configure OAuth",
    )

    skip_option = ui.ask_select(
        "How would you like to handle Google Cloud setup?",
        choices=[
            {"name": "Full guided setup with gcloud CLI (recommended)", "value": "full"},
            {"name": "I already have OAuth credentials, just enter them", "value": "creds_only"},
            {"name": "Skip for now (configure later via admin UI)", "value": "skip"},
        ],
    )

    if skip_option == "skip":
        ui.info("You can configure Google OAuth later in the admin panel.")
        return "skip"

    if skip_option == "creds_only":
        # Just collect credentials
        # Ask for domain first if not set (needed for redirect URIs)
        if not state.domain:
            state.domain = ui.ask_text(
                "Enter your domain (e.g., email.example.com):",
                default="localhost",
            )
            state.use_https = state.domain != "localhost"
        setup_oauth_credentials(state)
        verify_google_setup(state)
        return None

    # Full setup path
    gcloud_ok = setup_gcloud_cli(state)
    if not gcloud_ok:
        ui.warning("Continuing without gcloud automation.")
        # Still allow manual credential entry
        if not state.domain:
            state.domain = ui.ask_text(
                "Enter your domain (e.g., email.example.com):",
                default="localhost",
            )
            state.use_https = state.domain != "localhost"
        setup_oauth_credentials(state)
        verify_google_setup(state)
        return None

    # Project setup
    setup_project(state)

    # Enable APIs
    enable_apis(state)

    # OAuth consent screen
    setup_oauth_consent(state)

    # Ask for domain before credentials (needed for redirect URIs)
    if not state.domain:
        state.domain = ui.ask_text(
            "Enter your domain (e.g., email.example.com):",
            default="localhost",
        )
        state.use_https = state.domain != "localhost"

    # OAuth credentials
    setup_oauth_credentials(state)

    # Final verification
    verify_google_setup(state)

    return None
