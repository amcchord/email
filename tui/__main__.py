"""Entry point for `python -m tui`."""

import argparse
import asyncio
import sys


def main():
    parser = argparse.ArgumentParser(
        description="Mail TUI - Terminal email client",
    )
    parser.add_argument(
        "--ssh",
        nargs="?",
        const=True,
        default=False,
        metavar="PORT",
        help="Start SSH server (optional port, default from config)",
    )
    parser.add_argument(
        "--web",
        nargs="?",
        const=True,
        default=False,
        metavar="PORT",
        help="Start web server (optional port, default from config)",
    )
    args = parser.parse_args()

    if args.ssh is not False:
        from tui.config import TUIConfig
        from tui.servers.ssh import start_ssh_server

        config = TUIConfig.from_env()
        port = int(args.ssh) if isinstance(args.ssh, str) else config.ssh_port
        asyncio.run(
            start_ssh_server(
                host=config.web_host,
                port=port,
                host_key_path=config.ssh_host_key_path,
            )
        )
        sys.exit(0)

    if args.web is not False:
        from tui.config import TUIConfig
        from tui.servers.web import start_web_server

        config = TUIConfig.from_env()
        port = int(args.web) if isinstance(args.web, str) else config.web_port
        start_web_server(host=config.web_host, port=port)
        sys.exit(0)

    # Default: run Textual app directly in terminal
    from tui.app import MailApp

    app = MailApp()
    app.run()


if __name__ == "__main__":
    main()
