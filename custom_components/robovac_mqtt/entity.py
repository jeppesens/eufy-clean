"""Shared helpers for protocol-dependent entity support.

Devices speak one of two DPS protocols (see api/parser.update_state):
"scalar" (plain Tuya-style int/JSON, e.g. T2210/G50) or "novel" (Anker
length-prefixed protobuf, the default for everything else, including
"legacy"/"unknown" api types).

Entities declare which protocols they support via a ``supported_api_types``
attribute — a tuple of protocol names, or ``None`` (the default) for
universal entities. Platform setups pass their candidate entities through
:func:`filter_supported_entities` so unsupported entities are never added
to the registry (e.g. no scalar-only switches on X-series devices).
"""

from __future__ import annotations

from typing import TypeVar

from homeassistant.helpers.entity import Entity

from .coordinator import EufyCleanCoordinator

API_TYPE_NOVEL = "novel"
API_TYPE_SCALAR = "scalar"

_EntityT = TypeVar("_EntityT", bound=Entity)


def effective_api_type(api_type: str) -> str:
    """Map a cloud-reported api type onto the two supported DPS protocols.

    Anything that is not scalar (novel, legacy, unknown, ...) is parsed and
    commanded as novel, mirroring api/parser.update_state dispatch.
    """
    return API_TYPE_SCALAR if api_type == API_TYPE_SCALAR else API_TYPE_NOVEL


def filter_supported_entities(
    coordinator: EufyCleanCoordinator, entities: list[_EntityT]
) -> list[_EntityT]:
    """Return only the entities supported by the device's DPS protocol."""
    api_type = effective_api_type(coordinator.api_type)
    return [
        entity
        for entity in entities
        if (supported := getattr(entity, "supported_api_types", None)) is None
        or api_type in supported
    ]
