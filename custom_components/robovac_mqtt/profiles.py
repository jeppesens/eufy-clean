"""Per-model catalog of accessory lifespans and wire keys."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache

from .const import API_TYPE_LEGACY, API_TYPE_NOVEL, API_TYPE_SCALAR
from .proto.cloud.consumable_pb2 import ConsumableRequest


@dataclass(frozen=True, slots=True)
class AccessorySpec:
    """Specification for a consumable or maintenance accessory."""

    attr_name: str  # field on AccessoryState
    sensor_id: str
    sensor_name: str
    button_id: str
    button_name: str
    icon: str
    max_life_hours: int  # rated lifespan / maintenance interval, hours
    time_unit: str = "h"  # unit the device reports usage in: "h" novel/legacy, "m" scalar
    is_maintenance: bool = False  # clean-interval rather than wear replacement

    proto_type: int | None = None  # ConsumableRequest enum, novel DPS 168
    scalar_key: str | None = None  # key in scalar DPS 150 JSON
    legacy_key: str | None = None  # key in legacy DPS 116 JSON
    supported_api_types: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class DeviceProfile:
    """A model's protocol and accessory specifications."""

    model: str
    api_type: str
    accessories: Mapping[str, AccessorySpec] = field(default_factory=dict)


# Specs are shared by pointer between profiles; keep them frozen.
NOVEL_FILTER = AccessorySpec(
    attr_name="filter_usage",
    sensor_id="filter_remaining",
    sensor_name="Filter Remaining",
    button_id="_reset_filter",
    button_name="Reset Filter",
    icon="mdi:air-filter",
    max_life_hours=360,
    proto_type=ConsumableRequest.FILTER_MESH,
)

NOVEL_ROLLING_BRUSH = AccessorySpec(
    attr_name="main_brush_usage",
    sensor_id="main_brush_remaining",
    sensor_name="Rolling Brush Remaining",
    button_id="_reset_main_brush",
    button_name="Reset Rolling Brush",
    icon="mdi:broom",
    max_life_hours=360,
    proto_type=ConsumableRequest.ROLLING_BRUSH,
)

NOVEL_SIDE_BRUSH = AccessorySpec(
    attr_name="side_brush_usage",
    sensor_id="side_brush_remaining",
    sensor_name="Side Brush Remaining",
    button_id="_reset_side_brush",
    button_name="Reset Side Brush",
    icon="mdi:broom",
    max_life_hours=180,
    proto_type=ConsumableRequest.SIDE_BRUSH,
)

NOVEL_SENSOR = AccessorySpec(
    attr_name="sensor_usage",
    sensor_id="sensor_remaining",
    sensor_name="Sensor Remaining",
    button_id="_reset_sensors",
    button_name="Reset Sensors",
    icon="mdi:eye-outline",
    max_life_hours=60,
    is_maintenance=True,
    proto_type=ConsumableRequest.SENSOR,
)

NOVEL_SCRAPE = AccessorySpec(
    attr_name="scrape_usage",
    sensor_id="scrape_remaining",
    sensor_name="Cleaning Tray Remaining",
    button_id="_reset_scrape",
    button_name="Reset Cleaning Tray",
    icon="mdi:wiper",
    max_life_hours=30,
    is_maintenance=True,
    proto_type=ConsumableRequest.SCRAPE,
    supported_api_types=(API_TYPE_NOVEL,),
)

NOVEL_MOP = AccessorySpec(
    attr_name="mop_usage",
    sensor_id="mop_remaining",
    sensor_name="Mopping Cloth Remaining",
    button_id="_reset_mop",
    button_name="Reset Mopping Cloth",
    icon="mdi:water",
    max_life_hours=180,
    proto_type=ConsumableRequest.MOP,
    supported_api_types=(API_TYPE_NOVEL,),
)

# L60 SES (T2277) intervals, from the app's Accessories screen.
NOVEL_FILTER_200H = AccessorySpec(
    attr_name="filter_usage",
    sensor_id="filter_remaining",
    sensor_name="Filter Remaining",
    button_id="_reset_filter",
    button_name="Reset Filter",
    icon="mdi:air-filter",
    max_life_hours=200,
    proto_type=ConsumableRequest.FILTER_MESH,
)

NOVEL_SIDE_BRUSH_250H = AccessorySpec(
    attr_name="side_brush_usage",
    sensor_id="side_brush_remaining",
    sensor_name="Side Brush Remaining",
    button_id="_reset_side_brush",
    button_name="Reset Side Brush",
    icon="mdi:broom",
    max_life_hours=250,
    proto_type=ConsumableRequest.SIDE_BRUSH,
)

NOVEL_DUSTBAG_1440H = AccessorySpec(
    attr_name="dustbag_usage",
    sensor_id="dustbag_remaining",
    sensor_name="Dust Bag Remaining",
    button_id="_reset_dustbag",
    button_name="Reset Dust Bag",
    icon="mdi:delete",
    max_life_hours=1440,
    proto_type=ConsumableRequest.DUSTBAG,
    supported_api_types=(API_TYPE_NOVEL,),
)

SCALAR_FILTER = AccessorySpec(
    attr_name="filter_usage",
    sensor_id="filter_remaining",
    sensor_name="Filter Remaining",
    button_id="_reset_filter",
    button_name="Reset Filter",
    icon="mdi:air-filter",
    max_life_hours=200,
    time_unit="m",
    scalar_key="dust_filter",
)

SCALAR_ROLLING_BRUSH = AccessorySpec(
    attr_name="main_brush_usage",
    sensor_id="main_brush_remaining",
    sensor_name="Rolling Brush Remaining",
    button_id="_reset_main_brush",
    button_name="Reset Rolling Brush",
    icon="mdi:broom",
    max_life_hours=360,
    time_unit="m",
    scalar_key="roller_brush",
)

SCALAR_SIDE_BRUSH = AccessorySpec(
    attr_name="side_brush_usage",
    sensor_id="side_brush_remaining",
    sensor_name="Side Brush Remaining",
    button_id="_reset_side_brush",
    button_name="Reset Side Brush",
    icon="mdi:broom",
    max_life_hours=250,
    time_unit="m",
    scalar_key="side_brush",
)

SCALAR_SENSOR = AccessorySpec(
    attr_name="sensor_usage",
    sensor_id="sensor_remaining",
    sensor_name="Sensor Remaining",
    button_id="_reset_sensors",
    button_name="Reset Sensors",
    icon="mdi:eye-outline",
    max_life_hours=35,
    time_unit="m",
    is_maintenance=True,
    scalar_key="sensors",
)

LEGACY_FILTER_200H = AccessorySpec(
    attr_name="filter_usage",
    sensor_id="filter_remaining",
    sensor_name="Filter Remaining",
    button_id="_reset_filter",
    button_name="Reset Filter",
    icon="mdi:air-filter",
    max_life_hours=200,
    proto_type=ConsumableRequest.FILTER_MESH,
    legacy_key="FM",
)

LEGACY_ROLLING_BRUSH_360H = AccessorySpec(
    attr_name="main_brush_usage",
    sensor_id="main_brush_remaining",
    sensor_name="Rolling Brush Remaining",
    button_id="_reset_main_brush",
    button_name="Reset Rolling Brush",
    icon="mdi:broom",
    max_life_hours=360,
    proto_type=ConsumableRequest.ROLLING_BRUSH,
    legacy_key="RB",
)

LEGACY_SIDE_BRUSH_180H = AccessorySpec(
    attr_name="side_brush_usage",
    sensor_id="side_brush_remaining",
    sensor_name="Side Brush Remaining",
    button_id="_reset_side_brush",
    button_name="Reset Side Brush",
    icon="mdi:broom",
    max_life_hours=180,
    proto_type=ConsumableRequest.SIDE_BRUSH,
    legacy_key="SB",
)

LEGACY_DUSTBAG_50H = AccessorySpec(
    attr_name="dustbag_usage",
    sensor_id="dustbag_remaining",
    sensor_name="Dust Bag Remaining",
    button_id="_reset_dustbag",
    button_name="Reset Dust Bag",
    icon="mdi:delete-outline",
    max_life_hours=50,
    proto_type=ConsumableRequest.DUSTBAG,
    legacy_key="DB",
)


NOVEL_OMNI_ACCESSORIES: dict[str, AccessorySpec] = {
    "filter_usage": NOVEL_FILTER,
    "main_brush_usage": NOVEL_ROLLING_BRUSH,
    "side_brush_usage": NOVEL_SIDE_BRUSH,
    "sensor_usage": NOVEL_SENSOR,
    "scrape_usage": NOVEL_SCRAPE,
    "mop_usage": NOVEL_MOP,
}

NOVEL_VAC_MOP_ACCESSORIES: dict[str, AccessorySpec] = {
    "filter_usage": NOVEL_FILTER,
    "main_brush_usage": NOVEL_ROLLING_BRUSH,
    "side_brush_usage": NOVEL_SIDE_BRUSH,
    "sensor_usage": NOVEL_SENSOR,
    "mop_usage": NOVEL_MOP,
}

NOVEL_VACUUM_ONLY_ACCESSORIES: dict[str, AccessorySpec] = {
    "filter_usage": NOVEL_FILTER,
    "main_brush_usage": NOVEL_ROLLING_BRUSH,
    "side_brush_usage": NOVEL_SIDE_BRUSH,
    "sensor_usage": NOVEL_SENSOR,
}

# L60 SES: no mop, tray or sensor-cleaning interval; the station's dust bag
# is tracked instead.
NOVEL_L60_SES_ACCESSORIES: dict[str, AccessorySpec] = {
    "filter_usage": NOVEL_FILTER_200H,
    "main_brush_usage": NOVEL_ROLLING_BRUSH,
    "side_brush_usage": NOVEL_SIDE_BRUSH_250H,
    "dustbag_usage": NOVEL_DUSTBAG_1440H,
}

SCALAR_ACCESSORIES: dict[str, AccessorySpec] = {
    "filter_usage": SCALAR_FILTER,
    "main_brush_usage": SCALAR_ROLLING_BRUSH,
    "side_brush_usage": SCALAR_SIDE_BRUSH,
    "sensor_usage": SCALAR_SENSOR,
}

LEGACY_X8_PRO_ACCESSORIES: dict[str, AccessorySpec] = {
    "filter_usage": LEGACY_FILTER_200H,
    "main_brush_usage": LEGACY_ROLLING_BRUSH_360H,
    "side_brush_usage": LEGACY_SIDE_BRUSH_180H,
    "dustbag_usage": LEGACY_DUSTBAG_50H,
}

DEFAULT_NOVEL_ACCESSORIES = NOVEL_OMNI_ACCESSORIES
DEFAULT_SCALAR_ACCESSORIES = SCALAR_ACCESSORIES


MODEL_PROFILES: dict[str, DeviceProfile] = {
    "T2351": DeviceProfile(
        model="T2351",
        api_type=API_TYPE_NOVEL,
        accessories=NOVEL_OMNI_ACCESSORIES,
    ),
    "T2320": DeviceProfile(
        model="T2320",
        api_type=API_TYPE_NOVEL,
        accessories=NOVEL_OMNI_ACCESSORIES,
    ),
    "T2261": DeviceProfile(
        model="T2261",
        api_type=API_TYPE_NOVEL,
        accessories=NOVEL_OMNI_ACCESSORIES,
    ),
    "T2262": DeviceProfile(
        model="T2262",
        api_type=API_TYPE_NOVEL,
        accessories=NOVEL_OMNI_ACCESSORIES,
    ),
    "T2266": DeviceProfile(
        model="T2266",
        api_type=API_TYPE_LEGACY,
        accessories=LEGACY_X8_PRO_ACCESSORIES,
    ),
    "T2276": DeviceProfile(
        model="T2276",
        api_type=API_TYPE_LEGACY,
        accessories=LEGACY_X8_PRO_ACCESSORIES,
    ),

    "T2080": DeviceProfile(
        model="T2080",
        api_type=API_TYPE_NOVEL,
        accessories=NOVEL_OMNI_ACCESSORIES,
    ),
    "T2080A": DeviceProfile(
        model="T2080A",
        api_type=API_TYPE_NOVEL,
        accessories=NOVEL_OMNI_ACCESSORIES,
    ),
    "T2119": DeviceProfile(
        model="T2119",
        api_type=API_TYPE_LEGACY,
        accessories={},
    ),

    "T2267": DeviceProfile(
        model="T2267",
        api_type=API_TYPE_NOVEL,
        accessories=NOVEL_VACUUM_ONLY_ACCESSORIES,
    ),
    "T2268": DeviceProfile(
        model="T2268",
        api_type=API_TYPE_NOVEL,
        accessories=NOVEL_VAC_MOP_ACCESSORIES,
    ),
    "T2277": DeviceProfile(
        model="T2277",
        api_type=API_TYPE_NOVEL,
        accessories=NOVEL_L60_SES_ACCESSORIES,
    ),
    "T2278": DeviceProfile(
        model="T2278",
        api_type=API_TYPE_NOVEL,
        accessories=NOVEL_VAC_MOP_ACCESSORIES,
    ),
    "T2181": DeviceProfile(
        model="T2181",
        api_type=API_TYPE_NOVEL,
        accessories=NOVEL_VAC_MOP_ACCESSORIES,
    ),
    "T2182": DeviceProfile(
        model="T2182",
        api_type=API_TYPE_NOVEL,
        accessories=NOVEL_VAC_MOP_ACCESSORIES,
    ),
    "T2192": DeviceProfile(
        model="T2192",
        api_type=API_TYPE_NOVEL,
        accessories=NOVEL_VACUUM_ONLY_ACCESSORIES,
    ),
    "T2193": DeviceProfile(
        model="T2193",
        api_type=API_TYPE_NOVEL,
        accessories=NOVEL_VAC_MOP_ACCESSORIES,
    ),
    "T2194": DeviceProfile(
        model="T2194",
        api_type=API_TYPE_NOVEL,
        accessories=NOVEL_VAC_MOP_ACCESSORIES,
    ),
    "T2190": DeviceProfile(
        model="T2190",
        api_type=API_TYPE_LEGACY,
        accessories={},
    ),

    "T2210": DeviceProfile(
        model="T2210",
        api_type=API_TYPE_SCALAR,
        accessories=SCALAR_ACCESSORIES,
    ),
    "T2150": DeviceProfile(model="T2150", api_type=API_TYPE_LEGACY, accessories={}),
    "T2250": DeviceProfile(model="T2250", api_type=API_TYPE_LEGACY, accessories={}),
    "T2251": DeviceProfile(model="T2251", api_type=API_TYPE_LEGACY, accessories={}),
    "T2252": DeviceProfile(model="T2252", api_type=API_TYPE_LEGACY, accessories={}),
    "T2253": DeviceProfile(model="T2253", api_type=API_TYPE_LEGACY, accessories={}),
    "T2254": DeviceProfile(model="T2254", api_type=API_TYPE_LEGACY, accessories={}),
    "T2255": DeviceProfile(model="T2255", api_type=API_TYPE_LEGACY, accessories={}),
    "T2256": DeviceProfile(model="T2256", api_type=API_TYPE_LEGACY, accessories={}),
    "T2257": DeviceProfile(model="T2257", api_type=API_TYPE_LEGACY, accessories={}),
    "T2258": DeviceProfile(model="T2258", api_type=API_TYPE_LEGACY, accessories={}),
    "T2259": DeviceProfile(model="T2259", api_type=API_TYPE_LEGACY, accessories={}),
    "T2270": DeviceProfile(model="T2270", api_type=API_TYPE_LEGACY, accessories={}),
    "T2272": DeviceProfile(model="T2272", api_type=API_TYPE_LEGACY, accessories={}),
    "T2273": DeviceProfile(model="T2273", api_type=API_TYPE_LEGACY, accessories={}),

    "T2280": DeviceProfile(
        model="T2280",
        api_type=API_TYPE_NOVEL,
        accessories=NOVEL_OMNI_ACCESSORIES,
    ),
    "T2292": DeviceProfile(
        model="T2292",
        api_type=API_TYPE_NOVEL,
        accessories=NOVEL_VACUUM_ONLY_ACCESSORIES,
    ),
    "T1250": DeviceProfile(model="T1250", api_type=API_TYPE_LEGACY, accessories={}),
    "T2103": DeviceProfile(model="T2103", api_type=API_TYPE_LEGACY, accessories={}),
    "T2117": DeviceProfile(model="T2117", api_type=API_TYPE_LEGACY, accessories={}),
    "T2118": DeviceProfile(model="T2118", api_type=API_TYPE_LEGACY, accessories={}),
    "T2120": DeviceProfile(model="T2120", api_type=API_TYPE_LEGACY, accessories={}),
    "T2123": DeviceProfile(model="T2123", api_type=API_TYPE_LEGACY, accessories={}),
    "T2128": DeviceProfile(model="T2128", api_type=API_TYPE_LEGACY, accessories={}),
    "T2130": DeviceProfile(model="T2130", api_type=API_TYPE_LEGACY, accessories={}),
    "T2132": DeviceProfile(model="T2132", api_type=API_TYPE_LEGACY, accessories={}),
}


def _legacy_specs() -> list[AccessorySpec]:
    """Every accessory spec that carries a legacy DPS 116 key."""
    return [
        spec
        for profile in MODEL_PROFILES.values()
        for spec in profile.accessories.values()
        if spec.legacy_key
    ]


def legacy_consumable_fields() -> dict[str, str]:
    """Legacy DPS 116 key -> AccessoryState field, from the profile specs.

    DPS 116 is base64 JSON ``{"consumable":{"duration":{"SB":50,...}}}``;
    ``duration`` is hours used against the spec's ``max_life_hours``.
    """
    return {spec.legacy_key: spec.attr_name for spec in _legacy_specs() if spec.legacy_key}


def legacy_consumable_reset_key(proto_type: int) -> str | None:
    """Legacy DPS 116 key for a ConsumableRequest type, from the profile specs."""
    for spec in _legacy_specs():
        if spec.proto_type == proto_type:
            return spec.legacy_key
    return None


@lru_cache(maxsize=128)
def get_device_profile(model: str, api_type: str) -> DeviceProfile:
    """Return the profile for a model, falling back to protocol defaults."""
    profile = MODEL_PROFILES.get(model)
    if profile and profile.api_type == api_type:
        return profile

    if api_type == API_TYPE_SCALAR:
        return DeviceProfile(
            model=model,
            api_type=API_TYPE_SCALAR,
            accessories=DEFAULT_SCALAR_ACCESSORIES,
        )

    if api_type == API_TYPE_LEGACY:
        # empty accessory map: unknown legacy models would otherwise get phantom sensors
        return DeviceProfile(
            model=model,
            api_type=API_TYPE_LEGACY,
            accessories={},
        )

    return DeviceProfile(
        model=model,
        api_type=API_TYPE_NOVEL,
        accessories=DEFAULT_NOVEL_ACCESSORIES,
    )
