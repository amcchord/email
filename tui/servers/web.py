"""Web server that serves the Mail TUI via textual-serve.

Starts an HTTP server that renders the Textual application in
a web browser using WebSocket-based terminal emulation.
"""

from __future__ import annotations

import sys


def start_web_server(
    host: str = "0.0.0.0",
    port: int = 8022,
) -> None:
    """Start a web-based TUI server using textual-serve.

    Parameters
    ----------
    host:
        Network interface to bind to.
    port:
        TCP port for the HTTP server.
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

    print(f"Starting web TUI server on http://{host}:{port}")
    print("Open the URL in your browser to access the Mail TUI.")

    server = Server(
        "python -m tui",
        host=host,
        port=port,
        title="Mail TUI",
    )
    server.serve()
