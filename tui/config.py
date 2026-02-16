"""TUI configuration from environment variables."""

import os
from dataclasses import dataclass


@dataclass
class TUIConfig:
    """Configuration for the TUI application.

    All values can be overridden via environment variables with the TUI_ prefix.
    For example: TUI_API_BASE_URL, TUI_SSH_PORT, etc.
    """

    api_base_url: str = "http://localhost:8000/api"
    ssh_port: int = 2222
    ssh_host_key_path: str = "/opt/mail/data/tui_host_key"
    web_port: int = 8022
    web_host: str = "0.0.0.0"
    poll_interval: int = 30
    page_size: int = 50

    @classmethod
    def from_env(cls) -> "TUIConfig":
        """Create a TUIConfig from environment variables."""
        return cls(
            api_base_url=os.environ.get(
                "TUI_API_BASE_URL", cls.api_base_url
            ),
            ssh_port=int(os.environ.get("TUI_SSH_PORT", cls.ssh_port)),
            ssh_host_key_path=os.environ.get(
                "TUI_SSH_HOST_KEY_PATH", cls.ssh_host_key_path
            ),
            web_port=int(os.environ.get("TUI_WEB_PORT", cls.web_port)),
            web_host=os.environ.get("TUI_WEB_HOST", cls.web_host),
            poll_interval=int(
                os.environ.get("TUI_POLL_INTERVAL", cls.poll_interval)
            ),
            page_size=int(os.environ.get("TUI_PAGE_SIZE", cls.page_size)),
        )
