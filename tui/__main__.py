"""Entry point for `python -m tui`."""

import argparse
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
        print("SSH server: Not yet implemented (Phase 6)")
        sys.exit(0)

    if args.web is not False:
        print("Web server: Not yet implemented (Phase 6)")
        sys.exit(0)

    # Default: run Textual app directly in terminal
    from tui.app import MailApp

    app = MailApp()
    app.run()


if __name__ == "__main__":
    main()
