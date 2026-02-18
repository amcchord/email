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
import signal
import struct
import sys
import termios
import tty

import httpx

logger = logging.getLogger(__name__)

# Backend API base URL used for SSH-level auth validation
_API_BASE_URL = os.environ.get("TUI_API_BASE_URL", "http://localhost:8000/api")


def _authenticate_user(username: str, password: str) -> dict | None:
    """Validate credentials against the backend API synchronously.

    Returns a dict with ``access_token`` and ``refresh_token`` on success,
    or None on failure.
    """
    try:
        resp = httpx.post(
            f"{_API_BASE_URL}/auth/login",
            json={"username": username, "password": password},
            timeout=10.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "access_token": data.get("access_token", ""),
                "refresh_token": data.get("refresh_token", ""),
            }
    except Exception:
        logger.debug("SSH auth validation failed for %s", username, exc_info=True)
    return None


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

    # Map connection id -> auth tokens for passing from SSHServer to session handler
    _conn_tokens: dict[int, dict] = {}

    class TUISSHServer(asyncssh.SSHServer):
        """SSH server that optionally authenticates against the backend API.

        If the user provides valid credentials, tokens are passed through
        to skip the TUI login screen. If auth fails or no password is
        provided, the connection is still allowed and the TUI shows its
        own login screen with the device-code flow.
        """

        def __init__(self) -> None:
            super().__init__()
            self._conn = None

        def connection_made(self, conn: asyncssh.SSHServerConnection) -> None:
            peer = conn.get_extra_info("peername")
            logger.info("SSH connection from %s", peer)
            self._conn = conn

        def connection_lost(self, exc: Exception | None) -> None:
            if exc:
                logger.debug("SSH connection lost: %s", exc)
            # Clean up token mapping
            if self._conn is not None:
                _conn_tokens.pop(id(self._conn), None)

        def begin_auth(self, username: str) -> bool:
            # Return False = auth not required.
            # The TUI login screen handles auth via device-code or password.
            return False

        def password_auth_supported(self) -> bool:
            return True

        def validate_password(self, username: str, password: str) -> bool:
            # Try to authenticate -- if it works, store tokens for passthrough.
            # Always return True so the connection is never rejected.
            tokens = _authenticate_user(username, password)
            if tokens and self._conn is not None:
                _conn_tokens[id(self._conn)] = tokens
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

            # CRITICAL: Set raw mode on the slave fd BEFORE forking.
            # This disables echo in the PTY kernel driver so that mouse
            # tracking sequences from the SSH client are never echoed
            # back as visible garbage. Textual will set its own raw mode
            # later but this closes the race window during startup.
            tty.setraw(slave_fd)

            env = os.environ.copy()
            env["TERM"] = term_type
            env["COLUMNS"] = str(width)
            env["LINES"] = str(height)
            env["HOME"] = os.environ.get("HOME", "/opt/mail")
            env["PATH"] = "/opt/mail/venv/bin:" + env.get("PATH", "/usr/bin")

            # Pass auth tokens to the child so the TUI can skip the login screen
            conn = process.channel.get_connection()
            tokens = _conn_tokens.pop(id(conn), None)
            if tokens:
                env["TUI_ACCESS_TOKEN"] = tokens.get("access_token", "")
                env["TUI_REFRESH_TOKEN"] = tokens.get("refresh_token", "")

            # Mark this as running under our SSH server so the child
            # Textual app can detect it.
            env["TUI_SSH_SERVER"] = "1"

            # Fork a child process attached to the PTY
            child_pid = os.fork()
            if child_pid == 0:
                # ── Child process ──────────────────────────────────
                os.close(master_fd)
                os.setsid()
                fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
                os.dup2(slave_fd, 0)
                os.dup2(slave_fd, 1)
                os.dup2(slave_fd, 2)
                if slave_fd > 2:
                    os.close(slave_fd)

                # CRITICAL: Set raw mode on the actual stdin fd (fd 0)
                # AFTER dup2.  The raw mode we set on slave_fd earlier
                # may be lost when Python re-initializes the terminal
                # during startup.  Setting it here on fd 0 ensures the
                # PTY kernel driver has echo disabled right up until
                # os.execve(), closing the race window where mouse
                # escape sequences could be echoed as visible garbage.
                try:
                    tty.setraw(0)
                except Exception:
                    pass

                os.chdir("/opt/mail")
                os.execve(python, [python, "-m", "tui"], env)
                os._exit(1)

            # ── Parent process ─────────────────────────────────────
            os.close(slave_fd)

            # IMMEDIATELY tell the SSH client's terminal to stop sending
            # mouse events. The user's terminal may have mouse tracking
            # left on from a previous session. We disable ALL mouse modes,
            # then clear the screen. Textual will re-enable the modes it
            # needs once it starts up.
            disable_mouse = (
                "\033[?1000l"   # Disable X10 mouse
                "\033[?1002l"   # Disable cell-motion tracking
                "\033[?1003l"   # Disable all-motion tracking
                "\033[?1006l"   # Disable SGR extended mouse
                "\033[?1015l"   # Disable urxvt extended mouse
                "\033[2J"       # Clear screen
                "\033[H"        # Cursor home
            )
            process.stdout.write(disable_mouse)

            loop = asyncio.get_event_loop()

            # Make master_fd non-blocking
            flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
            fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

            # ── Terminal resize handler ────────────────────────────
            # Relay window size changes from SSH client to the PTY
            # by monkey-patching the process's terminal_size_changed callback.
            _master = master_fd
            _child = child_pid

            _orig_tsc = getattr(process, 'terminal_size_changed', None)

            def _on_terminal_resize(w, h, pixw, pixh):
                try:
                    ws = struct.pack("HHHH", h, w, pixw, pixh)
                    fcntl.ioctl(_master, termios.TIOCSWINSZ, ws)
                    if _child:
                        os.kill(_child, signal.SIGWINCH)
                    logger.debug("Relayed terminal resize %dx%d to child %s", w, h, _child)
                except OSError:
                    logger.debug("Failed to relay terminal resize", exc_info=True)

            # Override the terminal_size_changed method so asyncssh
            # calls our handler instead of raising TerminalSizeChanged.
            process.terminal_size_changed = _on_terminal_resize

            # ── PTY master → SSH channel ───────────────────────────
            read_done = asyncio.Event()
            # Gate: set when Textual has entered application mode
            # (alternate screen buffer). Until then, SSH input is discarded.
            # We check for multiple signals: alternate screen, mouse enable,
            # or cursor hide -- any of these indicates Textual is running.
            app_ready = asyncio.Event()
            # We gate input forwarding until Textual has FULLY initialized
            # the terminal.  Textual's startup order is:
            #   1. \x1b[?1049h  -- switch to alternate screen
            #   2. tcsetattr()  -- disable echo, set raw mode
            #   3. \x1b[?25l    -- hide cursor
            # We MUST wait for step 3 (cursor hide) because echo is only
            # disabled after step 2.  If we forward input after step 1
            # but before step 2, the PTY kernel echoes characters back.
            _APP_READY_MARKERS = (
                b'\x1b[?25l',     # Cursor hide (comes AFTER raw mode)
            )

            # Sequences to strip from PTY output going to the SSH client.
            # These are terminal mode changes that cause problems over SSH:
            #   \x1b[?1004h  -- enable focus reporting (causes bell on focus/unfocus)
            #   \x1b[>1u     -- enable kitty keyboard protocol (not supported by all terms)
            #   \x1b[?2026   -- synchronized output queries
            _OUTPUT_STRIP = (
                b'\x1b[?1004h',    # Focus reporting on
                b'\x1b[?1004l',    # Focus reporting off
                b'\x1b[>1u',       # Kitty keyboard protocol
                b'\x1b[<1u',       # Kitty keyboard protocol disable
            )

            def _filter_output(data: bytes) -> bytes:
                """Remove problematic escape sequences from PTY output."""
                for seq in _OUTPUT_STRIP:
                    data = data.replace(seq, b'')
                return data

            def on_pty_readable():
                try:
                    data = os.read(master_fd, 65536)
                    if data:
                        if not app_ready.is_set():
                            for marker in _APP_READY_MARKERS:
                                if marker in data:
                                    app_ready.set()
                                    break
                            if not app_ready.is_set():
                                return
                        data = _filter_output(data)
                        if data:
                            process.stdout.write(
                                data.decode("utf-8", errors="replace")
                            )
                    else:
                        read_done.set()
                except OSError:
                    read_done.set()

            loop.add_reader(master_fd, on_pty_readable)

            # ── SSH channel → PTY master ───────────────────────────
            async def ssh_to_pty():
                try:
                    # Wait until Textual has entered application mode.
                    # Any mouse events sent by the client terminal during
                    # startup are read and DISCARDED to prevent echo garbage.
                    while not app_ready.is_set():
                        try:
                            data = await asyncio.wait_for(
                                process.stdin.read(65536), timeout=0.1
                            )
                            if not data:
                                return
                            # Discard -- this is mouse garbage from startup
                        except asyncio.TimeoutError:
                            continue

                    # Also drain any remaining buffered input that arrived
                    # just as app_ready was set
                    try:
                        while True:
                            data = await asyncio.wait_for(
                                process.stdin.read(65536), timeout=0.05
                            )
                            if not data:
                                return
                            # Still discarding
                    except asyncio.TimeoutError:
                        pass

                    # Small safety margin: ensure the tcsetattr (raw mode)
                    # has fully taken effect on the PTY before we forward
                    # any input.  Without this, a fast typist could get
                    # characters echoed during the few ms between
                    # \x1b[?25l and the actual raw mode activation.
                    await asyncio.sleep(0.05)

                    # Now forward input normally.
                    # Filter out terminal responses and focus events that
                    # the SSH client's terminal sends back in response to
                    # Textual's query sequences.  These would otherwise be
                    # interpreted as keystrokes and displayed on screen.
                    import re
                    # Patterns to strip from SSH input:
                    #   \x1b[I / \x1b[O  -- focus in/out events
                    #   \x1b[?...c       -- DA1 response
                    #   \x1b[>...c       -- DA2 response
                    #   \x1b[?...n       -- DSR response
                    #   \x1b[...R        -- cursor position report
                    #   \x1b[?2048;...   -- in-band resize response
                    #   \x1b[?...;...$y  -- DECRPM response
                    #   \x1b P...ST      -- DCS response (device control)
                    #   \x1b]...ST       -- OSC response
                    _STRIP_RE = re.compile(
                        rb'\x1b\[I'             # Focus in
                        rb'|\x1b\[O'            # Focus out
                        rb'|\x1b\[\?[\d;]*c'    # DA1 response
                        rb'|\x1b\[>[\d;]*c'     # DA2 response
                        rb'|\x1b\[\?[\d;]*n'    # DSR response
                        rb'|\x1b\[\d+;\d+R'     # CPR (cursor position report)
                        rb'|\x1b\[\?[\d;]*\$y'  # DECRPM response
                        rb'|\x1bP[^\x1b]*\x1b\\' # DCS response
                        rb'|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)' # OSC response
                    )

                    while True:
                        data = await process.stdin.read(65536)
                        if not data:
                            break
                        raw = data.encode("utf-8") if isinstance(data, str) else data
                        # Strip terminal query responses and focus events
                        raw = _STRIP_RE.sub(b'', raw)
                        if raw:
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
            line_editor=False,
            line_echo=False,
        )
        logger.info("SSH server listening on %s:%d", host, port)
        print(f"SSH server listening on {host}:{port}")
        print(f"Connect with: ssh -p {port} user@{host}")

        # Keep running forever
        await asyncio.Event().wait()

    await _start()
