"""
Test runner wrapper for Windows.

pytest-homeassistant-custom-component has two Windows incompatibilities:

  1. runner.py does a top-level 'import fcntl', a POSIX-only module.

  2. The HA plugin calls pytest_socket.disable_socket() to block all network
     I/O.  On Windows, the asyncio event loop uses an AF_INET socketpair for
     its internal self-pipe, so socket creation is blocked before any test
     even starts.

Fix: install mock stubs for both before pytest (and the HA plugin) loads.
Our unit tests (parser, commands, map_stream, utils) make no real network
calls, so bypassing the socket guard here is safe.

Usage:
    python run_tests.py tests/test_map_stream.py -v
    python run_tests.py tests/test_commands.py tests/test_utils.py -v
"""
import sys
from unittest.mock import MagicMock

# ── 1. Mock POSIX-only modules ───────────────────────────────────────────────
for _mod in ("fcntl", "grp", "termios", "tty", "pty", "resource"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

_fcntl = sys.modules["fcntl"]
_fcntl.LOCK_EX = 2  # type: ignore[attr-defined]
_fcntl.LOCK_SH = 1  # type: ignore[attr-defined]
_fcntl.LOCK_NB = 4  # type: ignore[attr-defined]
_fcntl.LOCK_UN = 8  # type: ignore[attr-defined]

# ── 2. Stub out pytest_socket before the HA plugin imports it ────────────────
# The HA plugin calls disable_socket() at session start, which replaces
# socket.socket with a version that raises SocketBlockedError on __new__.
# On Windows, even the asyncio event loop's internal socketpair triggers this.
# Replacing pytest_socket with a no-op stub prevents that.
if sys.platform == "win32" and "pytest_socket" not in sys.modules:
    import types as _types
    _ps = _types.ModuleType("pytest_socket")
    _ps.disable_socket = lambda *a, **kw: None          # type: ignore[attr-defined]
    _ps.enable_socket = lambda *a, **kw: None           # type: ignore[attr-defined]
    _ps.socket_allow_hosts = lambda *a, **kw: None      # type: ignore[attr-defined]
    _ps.SocketBlockedError = OSError                    # type: ignore[attr-defined]
    sys.modules["pytest_socket"] = _ps

import pytest  # noqa: E402  # pylint: disable=wrong-import-position

sys.exit(pytest.main(sys.argv[1:]))
