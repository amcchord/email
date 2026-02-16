"""Web-based TUI server using textual-serve.

Serves the Mail TUI in a browser via WebSocket-based terminal rendering.
"""

from __future__ import annotations

import sys


def start_web_server(
    host: str = "0.0.0.0",
    port: int = 8022,
    public_url: str | None = None,
) -> None:
    """Start the web-based TUI server.

    Parameters
    ----------
    host:
        Network interface to bind to.
    port:
        TCP port for the web server.
    public_url:
        The public URL where this server is accessible (e.g., https://email.mcchord.net/tui).
        If not set, textual-serve will generate URLs based on host:port.
    """
    try:
        from textual_serve.server import Server
    except ImportError:
        print(
            "textual-serve is required for the web server.\n"
            "Install it with: pip install textual-serve>=1.1.0",
            file=sys.stderr,
        )
        sys.exit(1)

    python = sys.executable or "/opt/mail/venv/bin/python"
    command = f"{python} -m tui"

    print(f"Starting web TUI server on http://{host}:{port}")
    print("Open the URL in your browser to access the Mail TUI.")

    server = Server(
        command,
        host=host,
        port=port,
        title="Mail TUI",
        public_url=public_url,
    )
    server.serve()
