"""Python half of the golden grid-raster contract.

The JS half (``tests/frontend/golden.test.mjs``) decodes
``tests/frontend/fixtures/golden_render.json`` with the shipped client renderer and
asserts every cell agrees with the server. That check is only ever as good as the
fixture, so this module does the two things the JS side cannot:

1. **Staleness** — regenerate the fixture and fail if it drifted. Without this a
   change to ``build_map_geometry`` or to ``render_map_png``'s colour rule would
   leave the JS suite passing against an outdated contract, which is precisely the
   failure the cross-language check exists to prevent.
2. **Provenance** — assert the fixture's "expected" colours are the ones a *real*
   ``render_map_png`` call produces. ``generate_golden_fixture.server_cell_colors``
   restates the renderer's step-1 loop (it has to: the renderer returns a PNG with
   the overlays already burned in and the frame already flipped), so on its own it
   is a second implementation that could drift from the first. Comparing it to an
   actual render at scale 1, with every overlay stripped, closes that loop.

Regenerate with: ``PYTHONPATH=. python3 tests/generate_golden_fixture.py``
"""
from __future__ import annotations

import base64
import copy
import dataclasses
import io
import json
import zlib

import pytest
from PIL import Image

from custom_components.robovac_mqtt.api.map_stream import (
    _PIXEL_COLORS,
    _ROOM_PALETTE,
    MapData,
    render_map_png,
)
from tests.generate_golden_fixture import (
    FIXTURE,
    _cases,
    build,
    server_cell_classes,
    server_cell_colors,
)


def _stored() -> dict:
    assert FIXTURE.exists(), (
        f"{FIXTURE} is missing — run "
        "`PYTHONPATH=. python3 tests/generate_golden_fixture.py`"
    )
    return json.loads(FIXTURE.read_text())


_DEFLATED_PAYLOAD = ("occupancy", "rooms_grid")
_DEFLATED_PLANES = ("expected_rgb", "expected_class")


def _inflate(b64: str) -> bytes:
    return zlib.decompress(base64.b64decode(b64))


def _inflated(doc: dict) -> dict:
    """The fixture with every deflated plane decoded.

    zlib builds (stock zlib, zlib-ng) emit different, equally valid streams for the
    same bytes, so the planes are compared, not their encodings.
    """
    out = copy.deepcopy(doc)
    for case in out["cases"]:
        for key in _DEFLATED_PAYLOAD:
            case["payload"][key] = _inflate(case["payload"][key])
        for key in _DEFLATED_PLANES:
            case[key] = _inflate(case[key])
    return out


@pytest.mark.parametrize("level", [9, 1], ids=["fixture-encoder", "other-encoder"])
def test_golden_fixture_is_current(monkeypatch, level):
    """The fixture the JS suite validates against must describe the code as it is now.

    Neither suite can run the other's language, so the fixture is the only channel
    between them and a stale one is a silently broken check rather than a failing one.
    Level 1 stands in for a zlib build that encodes the same planes differently.
    """
    real = zlib.compress
    monkeypatch.setattr(zlib, "compress", lambda data, _level=-1: real(data, level))
    rebuilt = build()
    if level != 9:
        assert rebuilt != _stored(), "the other encoder must change some stream"
    assert _inflated(_stored()) == _inflated(rebuilt), (
        "golden_render.json is stale — regenerate it with "
        "`PYTHONPATH=. python3 tests/generate_golden_fixture.py` and re-run the JS "
        "suite (cd tests/frontend && npm test), which verifies the client renderer "
        "still matches render_map_png"
    )


@pytest.mark.parametrize("case_name", list(_cases()))
def test_expected_colors_are_render_map_png_s_own(case_name: str):
    """The fixture's expected colours equal a real ``render_map_png`` raster.

    ``render_map_png`` bakes in a Y-flip and a NEAREST resize to ``max_px``. Passing
    ``max_px = max(width, height)`` makes ``scale`` exactly 1.0, so the resize is
    skipped entirely and un-flipping the result recovers the pre-flip colour list
    byte for byte. Every overlay is stripped from the ``MapData`` first — room
    names (labels), walls and zones — and no dock/robot/trail is passed, so nothing
    is drawn over the grid.
    """
    _, map_data = _cases()[case_name]
    bare = dataclasses.replace(
        map_data,
        room_names={},
        virtual_walls=[],
        forbidden_zones=[],
        ban_mop_zones=[],
        dock_pixel=None,
    )
    png = render_map_png(bare, max_px=max(bare.width, bare.height))
    img = Image.open(io.BytesIO(png)).convert("RGB")
    assert img.size == (bare.width, bare.height), (
        "max_px = max(w, h) must give scale 1.0 and skip the resize"
    )
    flat = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes()
    rendered = [tuple(flat[i : i + 3]) for i in range(0, len(flat), 3)]

    expected = server_cell_colors(map_data)
    assert len(rendered) == len(expected)
    for i, (got, want) in enumerate(zip(rendered, expected)):
        if got != want:  # pragma: no cover - only on a real divergence
            row, col = divmod(i, bare.width)
            pytest.fail(
                f"{case_name}: cell {i} (col {col}, row {row}) renders {got}, "
                f"fixture says {want}"
            )


@pytest.mark.parametrize("case_name", list(_cases()))
def test_class_plane_and_rgb_plane_describe_the_same_cells(case_name: str):
    """The two expected planes are two views of one decision, and must not disagree.

    The JS side leans on both: the RGB plane for the classes whose colours the two
    ends share exactly, the class plane for room fills (whose hues deliberately
    differ). If one said "room" where the other said "wall" the JS assertions would
    contradict each other with no way to tell which was right.
    """
    _, map_data = _cases()[case_name]

    base = _stored()["room_class_base"]
    colors = server_cell_colors(map_data)
    classes = server_cell_classes(map_data)
    assert len(colors) == len(classes)
    for i, (color, cls) in enumerate(zip(colors, classes)):
        if cls >= base:
            rid = cls - base + map_data.room_id_offset  # back to the stored id
            want = _ROOM_PALETTE[1 + (rid - 1) % (len(_ROOM_PALETTE) - 1)]
        else:
            want = _PIXEL_COLORS[cls]
        assert color == want, f"{case_name}: cell {i} class {cls} vs colour {color}"


def test_fixture_covers_the_registration_details_it_claims_to():
    """Guard the fixture's own coverage — a case that stopped exercising its point.

    Each of these was chosen because it reaches something a flat 16x16 random grid
    cannot: a non-zero room-mask offset, both ``room_id_offset`` regimes, a real
    room id of 0, and cells that fall outside the mask entirely.
    """
    cases = {c["name"]: c for c in _stored()["cases"]}

    offset_case = _cases()["mask_origin_offset"][1]
    res = offset_case.resolution or 5
    ro_dx = round((offset_case.origin_x - offset_case.room_outline_origin_x) / res)
    ro_dy = round((offset_case.origin_y - offset_case.room_outline_origin_y) / res)
    assert (ro_dx, ro_dy) != (0, 0), "the offset case must actually offset the mask"
    assert (
        offset_case.room_outline_width < offset_case.width
        and offset_case.room_outline_height < offset_case.height
    ), "the mask must be smaller than the grid so out-of-mask cells exist"

    assert cases["apartment"]["room_id_offset"] == 1
    assert cases["novel_offset0"]["room_id_offset"] == 0
    # Legacy room id 0 is a real room (the T2266's Hallway) and has to be in here.
    assert any(r["id"] == 0 for r in cases["apartment"]["payload"]["rooms"])
    assert all(r["id"] != 0 for r in cases["novel_offset0"]["payload"]["rooms"])

    combos = _cases()["all_combinations"][1]
    seen = set()
    occupancy = zlib.decompress(
        base64.b64decode(cases["all_combinations"]["payload"]["occupancy"])
    )
    rooms = zlib.decompress(
        base64.b64decode(cases["all_combinations"]["payload"]["rooms_grid"])
    )
    for i in range(combos.width * combos.height):
        seen.add((occupancy[i] >> 2 & 3, occupancy[i] & 3, rooms[i]))
    # 4 sub-types x 4 occupancy values x 4 stored ids, and stored id 0 appears with
    # every sub-type — a combination only reachable because the sub-type lives in
    # the mask byte rather than in rooms_grid.
    assert len(seen) == 4 * 4 * 4, f"only {len(seen)} of 64 combos"
    assert {s for s, _pv, r in seen if r == 0} == {0, 1, 2, 3}


def test_no_room_mask_case_takes_the_renderer_s_else_branch():
    """A map with no room mask must colour from the occupancy value alone.

    This is a separate code path in ``render_map_png`` (the ``else`` at
    ``map_stream.py:504``) and a separate one in ``buildGridImageData`` (every
    ``rooms_grid`` byte is 0), so it needs its own case rather than being assumed to
    fall out of the masked one.
    """
    map_data: MapData = _cases()["no_room_mask"][1]
    assert map_data.room_pixels is None
    classes = server_cell_classes(map_data)
    assert max(classes) < _stored()["room_class_base"], "no cell may be room-filled"
    grid = zlib.decompress(
        base64.b64decode(
            {c["name"]: c for c in _stored()["cases"]}["no_room_mask"]["payload"][
                "rooms_grid"
            ]
        )
    )
    assert set(grid) == {0}
