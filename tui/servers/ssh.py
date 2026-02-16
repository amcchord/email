"""SSH server that spawns a Mail TUI instance per connection.

Uses asyncssh to create an SSH server. Each connecting client gets
a PTY with a subprocess running ``python -m tui``, so the full
Textual application renders over the SSH channel.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)


async def start_ssh_server(
    host: str = "0.0.0.0",
    port: int = 2222,
    host_key_path: str = "/opt/mail/data/tui_host_key",
) -> None:
    """Start an SSH server that serves the Mail TUI.

    Parameters
    ----------
    host:
        Network interface to bind to.
    port:
        TCP port for the SSH server.
    host_key_path:
        Path to the ED25519 host key. Auto-generated if missing.
    """
    try:
        import asyncssh
    except ImportError:
        print(
            "asyncssh is required for the SSH server.\n"
            "Install it with: pip install asyncssh>=2.17.0",
            file=sys.stderr,
        )
        sys.exit(1)

    # Auto-generate host key if it doesn't exist
    os.makedirs(os.path.dirname(host_key_path), exist_ok=True)
    if not os.path.exists(host_key_path):
        logger.info("Generating ED25519 host key at %s", host_key_path)
        key = asyncssh.generate_private_key("ssh-ed25519")
        key.write_private_key(host_key_path)
        os.chmod(host_key_path, 0o600)
        logger.info("Host key generated")

    class TUISSHServer(asyncssh.SSHServer):
        """SSH server that accepts all connections.

        Real authentication happens at the TUI login screen, so the SSH
        layer allows any username/password combination through.
        """

        def connection_made(self, conn: asyncssh.SSHServerConnection) -> None:
            peer = conn.get_extra_info("peername")
            logger.info("SSH connection from %s", peer)

        def connection_lost(self, exc: Exception | None) -> None:
            if exc:
                logger.debug("SSH connection lost: %s", exc)

        def begin_auth(self, username: str) -> bool:
            # Return False = no auth required (login screen handles it)
            return False

        def password_auth_supported(self) -> bool:
            return True

        def validate_password(self, username: str, password: str) -> bool:
            # Accept any credentials - the TUI login screen handles real auth
            return True

    class TUISSHProcess(asyncssh.SSHServerProcess):  # type: ignore[type-arg]
        """Process handler that spawns ``python -m tui`` in a PTY."""

        async def begin(self) -> None:
            """Called when a session channel is opened."""
            try:
                # Get the Python interpreter path
                python = sys.executable or "python3"
                # Spawn the TUI as a subprocess
                term_type = self.get_terminal_type() or "xterm-256color"
                width, height = self.get_terminal_size()[:2]

                env = os.environ.copy()
                env["TERM"] = term_type
                env["COLUMNS"] = str(width)
                env["LINES"] = str(height)

                process = await asyncio.create_subprocess_exec(
                    python, "-m", "tui",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )

                # Pipe SSH channel <-> subprocess stdio
                async def pipe_to_process() -> None:
                    """Read from SSH stdin and write to subprocess stdin."""
                    try:
                        while True:
                            data = await self.stdin.read(4096)
                            if not data:
                                break
                            if process.stdin:
                                process.stdin.write(data.encode() if isinstance(data, str) else data)
                                await process.stdin.drain()
                    except (asyncio.CancelledError, ConnectionError):
                        pass
                    finally:
                        if process.stdin:
                            process.stdin.close()

                async def pipe_from_process() -> None:
                    """Read from subprocess stdout and write to SSH channel."""
                    try:
                        while True:
                            if process.stdout is None:
                                break
                            data = await process.stdout.read(4096)
                            if not data:
                                break
                            self.stdout.write(data.decode("utf-8", errors="replace"))
                    except (asyncio.CancelledError, ConnectionError):
                        pass

                # Run both pipes concurrently
                await asyncio.gather(
                    pipe_to_process(),
                    pipe_from_process(),
                    return_exceptions=True,
                )

                # Wait for subprocess to finish
                await process.wait()
                self.exit(process.returncode or 0)

            except Exception:
                logger.exception("Error in SSH session")
                self.exit(1)

    async def _start() -> None:
        await asyncssh.create_server(
            TUISSHServer,
            host=host,
            port=port,
            server_host_keys=[host_key_path],
            process_factory=lambda: TUISSHProcess(),  # type: ignore[call-arg]
        )
        logger.info("SSH server listening on %s:%d", host, port)
        print(f"SSH server listening on {host}:{port}")
        print(f"Connect with: ssh -p {port} user@{host}")

        # Keep running forever
        await asyncio.Event().wait()

    await _start()
