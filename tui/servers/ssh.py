"""SSH server that spawns a Mail TUI instance per connection.

Uses asyncssh to create an SSH server. Each connecting client gets
a real PTY with ``python -m tui``, so the full Textual application
renders correctly over the SSH channel.
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import pty
import struct
import sys
import termios

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
            return True

    async def handle_session(process: asyncssh.SSHServerProcess) -> None:
        """Handle an SSH session by spawning python -m tui in a real PTY."""
        master_fd = None
        child_pid = None
        try:
            python = sys.executable or "/opt/mail/venv/bin/python"
            term_type = process.get_terminal_type() or "xterm-256color"
            size = process.get_terminal_size()
            width = size[0] if size else 80
            height = size[1] if size else 24

            # Create a real PTY
            master_fd, slave_fd = pty.openpty()

            # Set terminal size on the PTY
            winsize = struct.pack("HHHH", height, width, 0, 0)
            fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

            env = os.environ.copy()
            env["TERM"] = term_type
            env["COLUMNS"] = str(width)
            env["LINES"] = str(height)
            env["HOME"] = os.environ.get("HOME", "/opt/mail")
            env["PATH"] = "/opt/mail/venv/bin:" + env.get("PATH", "/usr/bin")

            # Fork a child process attached to the PTY
            child_pid = os.fork()
            if child_pid == 0:
                # Child process
                os.close(master_fd)
                os.setsid()
                fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
                os.dup2(slave_fd, 0)
                os.dup2(slave_fd, 1)
                os.dup2(slave_fd, 2)
                if slave_fd > 2:
                    os.close(slave_fd)
                os.chdir("/opt/mail")
                os.execve(python, [python, "-m", "tui"], env)
                # execve never returns on success
                os._exit(1)

            # Parent process
            os.close(slave_fd)

            loop = asyncio.get_event_loop()

            # Make master_fd non-blocking
            flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
            fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

            # Read from PTY master → SSH channel
            read_done = asyncio.Event()

            def on_pty_readable():
                try:
                    data = os.read(master_fd, 65536)
                    if data:
                        process.stdout.write(data.decode("utf-8", errors="replace"))
                    else:
                        read_done.set()
                except OSError:
                    read_done.set()

            loop.add_reader(master_fd, on_pty_readable)

            # Read from SSH channel → PTY master
            async def ssh_to_pty():
                try:
                    while True:
                        data = await process.stdin.read(65536)
                        if not data:
                            break
                        raw = data.encode("utf-8") if isinstance(data, str) else data
                        os.write(master_fd, raw)
                except (OSError, asyncio.CancelledError, ConnectionError):
                    pass

            ssh_task = asyncio.create_task(ssh_to_pty())

            # Wait for child process to exit
            _, status = await loop.run_in_executor(None, os.waitpid, child_pid, 0)
            child_pid = None  # Already reaped
            exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else 1

            # Clean up
            loop.remove_reader(master_fd)
            ssh_task.cancel()
            try:
                await ssh_task
            except asyncio.CancelledError:
                pass

            process.exit(exit_code)

        except Exception:
            logger.exception("Error in SSH session")
            process.exit(1)
        finally:
            if master_fd is not None:
                try:
                    os.close(master_fd)
                except OSError:
                    pass
            if child_pid is not None:
                try:
                    os.kill(child_pid, 9)
                    os.waitpid(child_pid, 0)
                except OSError:
                    pass

    async def _start() -> None:
        await asyncssh.create_server(
            TUISSHServer,
            host=host,
            port=port,
            server_host_keys=[host_key_path],
            process_factory=handle_session,
        )
        logger.info("SSH server listening on %s:%d", host, port)
        print(f"SSH server listening on {host}:{port}")
        print(f"Connect with: ssh -p {port} user@{host}")

        # Keep running forever
        await asyncio.Event().wait()

    await _start()
