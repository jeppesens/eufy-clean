"""Model-specific screen codes and shared HA error attributes.

S1 Pro mappings are factual code pairs from eufy Clean 3.20.0 (1042),
assets/green_lantern/T2080A_prompt_json.json and English string resources.
The older protobuf enum named t2080 uses a different numbering scheme.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .const import S1_PRO_ERROR_DESCRIPTIONS, S1_PRO_MODELS, S1_PRO_SCREEN_CODES

if TYPE_CHECKING:
    from .models import VacuumState


def screen_error_code(code: int, model: str) -> str | int:
    """Return a verified screen code, keeping other models/numbers unchanged."""
    if model.upper() in S1_PRO_MODELS:
        return S1_PRO_SCREEN_CODES.get(code, code)
    return code


def s1_error_message(code: int, model: str) -> str | None:
    """Describe a verified S1 code without guessing another model's mapping."""
    label = screen_error_code(code, model)
    if isinstance(label, str):
        return S1_PRO_ERROR_DESCRIPTIONS.get(label, f"Robot fault ({label})")
    return None


def error_attributes(state: VacuumState) -> dict[str, Any]:
    """Expose current errors and the previous error without losing raw numbers."""
    return {
        "error_code": screen_error_code(state.error_code, state.device_model),
        "error_code_raw": state.error_code,
        "error_codes": [screen_error_code(c, state.device_model) for c in state.error_codes],
        "error_codes_raw": list(state.error_codes),
        "error_active": state.activity == "error" and bool(state.error_code),
        "last_error_code": screen_error_code(state.last_error_code, state.device_model),
        "last_error_code_raw": state.last_error_code,
        "last_error_message": state.last_error_message,
    }


def error_sensor_value(state: VacuumState) -> str:
    """A short error code suitable for HA state triggers."""
    return str(screen_error_code(state.error_code, state.device_model)) if state.error_code else "None"
