"""Global fixtures for robovac_mqtt integration tests."""

import sys
from unittest.mock import MagicMock

import pytest

# homeassistant.components.camera imports turbojpeg at module level, which is a
# system library not available in the test environment.  Mock it before HA loads.
if "turbojpeg" not in sys.modules:
    sys.modules["turbojpeg"] = MagicMock()


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations defined in the test dir."""
    yield
