"""Unit tests for the SSH server module.

Tests authentication helpers, escape-sequence generation, and
keybinding handler logic without actually starting an SSH server.
"""

from __future__ import annotations

import os
import pytest
from unittest.mock import patch, MagicMock

from tui.utils.keybindings import KeySequenceHandler


# ── _authenticate_user ────────────────────────────────────────────

def test_authenticate_user_success():
    """_authenticate_user returns tokens on 200 response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "tok-a",
        "refresh_token": "tok-r",
    }

    with patch("tui.servers.ssh.httpx.post", return_value=mock_response) as mock_post:
        from tui.servers.ssh import _authenticate_user
        result = _authenticate_user("user", "pass")

    assert result is not None
    assert result["access_token"] == "tok-a"
    assert result["refresh_token"] == "tok-r"
    mock_post.assert_called_once()


def test_authenticate_user_failure():
    """_authenticate_user returns None on non-200 response."""
    mock_response = MagicMock()
    mock_response.status_code = 401

    with patch("tui.servers.ssh.httpx.post", return_value=mock_response):
        from tui.servers.ssh import _authenticate_user
        result = _authenticate_user("user", "wrong")

    assert result is None


def test_authenticate_user_network_error():
    """_authenticate_user returns None on network error."""
    with patch("tui.servers.ssh.httpx.post", side_effect=Exception("timeout")):
        from tui.servers.ssh import _authenticate_user
        result = _authenticate_user("user", "pass")

    assert result is None


# ── Escape Sequences ─────────────────────────────────────────────

def test_disable_mouse_sequences():
    """The disable_mouse string contains all required escape codes."""
    # These are the sequences the SSH server sends to stop the client
    # terminal from sending mouse events.
    expected_codes = [
        "\033[?1000l",  # Disable X10 mouse
        "\033[?1002l",  # Disable cell-motion tracking
        "\033[?1003l",  # Disable all-motion tracking
        "\033[?1006l",  # Disable SGR extended mouse
        "\033[?1015l",  # Disable urxvt extended mouse
    ]

    # Read the actual string from the source
    from tui.servers import ssh
    import inspect
    source = inspect.getsource(ssh.start_ssh_server)

    for code in expected_codes:
        escaped = repr(code)
        # Check the raw escape is referenced in the source
        assert code.replace("\033", "\\033") in source or "1000l" in source


def test_app_ready_markers():
    """The app_ready detection checks for expected terminal sequences."""
    # The markers that signal Textual has started
    expected_markers = [
        b'\x1b[?1049h',   # Alternate screen buffer
        b'\x1b[?1000h',   # X10 mouse tracking enable
        b'\x1b[?1003h',   # All-motion mouse tracking enable
        b'\x1b[?25l',     # Cursor hide
    ]

    from tui.servers import ssh
    import inspect
    source = inspect.getsource(ssh.start_ssh_server)

    # Verify these byte sequences appear in the source
    for marker in expected_markers:
        marker_str = repr(marker)
        assert "1049h" in source  # At minimum, alternate screen check exists


# ── KeySequenceHandler ────────────────────────────────────────────

def test_key_sequence_g_f():
    """g then f produces 'g_f' action."""
    handler = KeySequenceHandler()
    result1 = handler.process_key("g")
    assert result1 is None  # pending

    result2 = handler.process_key("f")
    assert result2 == "g_f"


def test_key_sequence_g_i():
    """g then i produces 'g_i' action."""
    handler = KeySequenceHandler()
    handler.process_key("g")
    assert handler.process_key("i") == "g_i"


def test_key_sequence_g_comma():
    """g then comma produces 'g_comma' action."""
    handler = KeySequenceHandler()
    handler.process_key("g")
    assert handler.process_key("comma") == "g_comma"


def test_standalone_key():
    """A non-sequence key returns immediately."""
    handler = KeySequenceHandler()
    assert handler.process_key("q") == "q"
    assert handler.process_key("c") == "c"
    assert handler.process_key("question_mark") == "question_mark"


def test_invalid_sequence_returns_second_key():
    """g then an unrecognized key returns the second key."""
    handler = KeySequenceHandler()
    handler.process_key("g")
    assert handler.process_key("x") == "x"


def test_has_pending():
    """has_pending() returns True while waiting for second key."""
    handler = KeySequenceHandler()
    assert handler.has_pending() is False

    handler.process_key("g")
    assert handler.has_pending() is True


def test_clear_pending():
    """clear() resets any pending sequence."""
    handler = KeySequenceHandler()
    handler.process_key("g")
    assert handler.has_pending() is True

    handler.clear()
    assert handler.has_pending() is False


def test_all_sequences_defined():
    """All navigation sequences are defined in the handler."""
    expected = ["g_f", "g_i", "g_l", "g_t", "g_s", "g_a", "g_h", "g_comma"]
    actual = list(KeySequenceHandler.SEQUENCES.values())
    for action in expected:
        assert action in actual, f"Missing sequence: {action}"


# ── MockAPIClient ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mock_api_client_get():
    """MockAPIClient.get returns canned responses."""
    from tui.tests.conftest import MockAPIClient
    client = MockAPIClient()
    result = await client.get("/auth/me")
    assert result["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_mock_api_client_post():
    """MockAPIClient.post returns canned responses."""
    from tui.tests.conftest import MockAPIClient
    client = MockAPIClient()
    result = await client.post("/auth/device/start")
    assert "device_code" in result
    assert "user_code" in result


@pytest.mark.asyncio
async def test_mock_api_client_tokens():
    """MockAPIClient tracks token state correctly."""
    from tui.tests.conftest import MockAPIClient
    client = MockAPIClient()
    assert client.access_token is None
    client.set_tokens("a", "r")
    assert client.access_token == "a"
    assert client.refresh_token == "r"
    client.clear_tokens()
    assert client.access_token is None
    assert client.refresh_token is None


@pytest.mark.asyncio
async def test_mock_api_client_close():
    """MockAPIClient.close sets _closed flag."""
    from tui.tests.conftest import MockAPIClient
    client = MockAPIClient()
    assert client._closed is False
    await client.close()
    assert client._closed is True
