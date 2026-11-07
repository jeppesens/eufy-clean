"""Unit tests for api/tuya_storage.py: the Tuya cloud-storage map fetch."""

from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

import pytest

from custom_components.robovac_mqtt.api import tuya_storage
from custom_components.robovac_mqtt.api.tuya_storage import (
    _MAX_MAP_BLOB_BYTES,
    StorageConfig,
    TuyaMapStorage,
    _file_entries,
    _sigv4_presign,
    choose_map_path,
    map_version_token,
)

from .test_tuya_map import build_blob, room_name_section, simple_grid

PREFIX = "7ffa93-100000001-0102030405060708090a/common"


def config() -> StorageConfig:
    return StorageConfig(
        access_key="TY.testaccesskey",
        secret_key="testsecretkey",
        token="tok/en+with/specials",
        bucket="ty-us-storage-permanent",
        endpoint="iotbing.com",
        region="iotbing.com",
    )


# ── Storage config parsing ──────────────────────────────────────────


def test_config_reads_the_field_names_the_app_uses():
    parsed = StorageConfig.from_response(
        {
            "ak": "A",
            "sk": "S",
            "token": "T",
            "bucket": "B",
            "endpoint": "E",
            "region": "R",
        }
    )
    assert parsed == StorageConfig("A", "S", "T", "B", "E", "R")


def test_config_accepts_alternate_spellings():
    parsed = StorageConfig.from_response(
        {"accessKeyId": "A", "secretKey": "S", "securityToken": "T",
         "bucketName": "B", "endPoint": "E"}
    )
    assert parsed is not None
    assert (parsed.access_key, parsed.bucket) == ("A", "B")


def test_config_falls_back_to_the_endpoint_for_region():
    """Tuya signs with the endpoint host as the region, not an AWS region."""
    parsed = StorageConfig.from_response(
        {"ak": "A", "sk": "S", "bucket": "B", "endpoint": "iotbing.com"}
    )
    assert parsed is not None and parsed.region == "iotbing.com"


def test_config_reads_a_nested_payload():
    parsed = StorageConfig.from_response(
        {"data": {"ak": "A", "sk": "S", "bucket": "B", "endpoint": "E"}}
    )
    assert parsed is not None and parsed.access_key == "A"


@pytest.mark.parametrize(
    "payload",
    [None, {}, [], {"ak": "A"}, {"ak": "A", "sk": "S"}],
    ids=["none", "empty", "list", "key-only", "no-bucket"],
)
def test_config_rejects_incomplete_credentials(payload):
    assert StorageConfig.from_response(payload) is None


# ── SigV4 presigning ────────────────────────────────────────────────
#
# The implementation was validated against a signature captured from
# com.oceanwing.battery.cam 6.0.80: with that session's real credentials it
# reproduces the app's X-Amz-Signature byte for byte. Those credentials are
# account-scoped, so the tests below pin the observable structure instead.


def test_presign_targets_bucket_dot_endpoint():
    url = _sigv4_presign(config(), f"/{PREFIX}/1771407019-show_map_3")
    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "ty-us-storage-permanent.iotbing.com"
    assert parsed.path == f"/{PREFIX}/1771407019-show_map_3"


def test_presign_emits_the_expected_query_parameters():
    url = _sigv4_presign(config(), f"/{PREFIX}/lay.bin", expires=86400)
    query = parse_qs(urlparse(url).query)
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert query["X-Amz-SignedHeaders"] == ["host"]
    assert query["X-Amz-Expires"] == ["86400"]
    assert query["X-Amz-Credential"][0].endswith("/iotbing.com/s3/aws4_request")
    assert query["X-Amz-Credential"][0].startswith("TY.testaccesskey/")
    assert len(query["X-Amz-Signature"][0]) == 64


def test_presign_percent_encodes_the_security_token():
    """The token routinely contains '/' and '+'; both must be escaped."""
    url = _sigv4_presign(config(), f"/{PREFIX}/lay.bin")
    raw_query = urlparse(url).query
    assert "tok%2Fen%2Bwith%2Fspecials" in raw_query
    assert parse_qs(raw_query)["X-Amz-Security-Token"] == ["tok/en+with/specials"]


def test_presign_omits_the_token_when_there_is_none():
    unscoped = StorageConfig("A", "S", "", "B", "E", "R")
    query = parse_qs(urlparse(_sigv4_presign(unscoped, "/x")).query)
    assert "X-Amz-Security-Token" not in query


def test_presign_signature_covers_the_path():
    """Two objects under the same credentials must not share a signature."""
    first = parse_qs(urlparse(_sigv4_presign(config(), "/a/one")).query)
    second = parse_qs(urlparse(_sigv4_presign(config(), "/a/two")).query)
    assert first["X-Amz-Signature"] != second["X-Amz-Signature"]


# ── File listing ────────────────────────────────────────────────────


@pytest.mark.parametrize("key", ["datas", "data", "list", "files", "result"])
def test_file_entries_unwraps_the_known_envelopes(key):
    assert _file_entries({key: [{"path": "a/b"}]}) == [{"path": "a/b"}]


def test_file_entries_of_an_unrecognised_shape_is_empty():
    assert not _file_entries({"unexpected": 1})


# ── Choosing which object to download ───────────────────────────────


def test_prefers_show_map_over_the_clean_record_copy():
    """Both carry the trailer; show_map is the current rendered snapshot."""
    paths = [f"{PREFIX}/100-map_3", f"{PREFIX}/100-show_map_3"]
    assert choose_map_path(paths, 3) == f"{PREFIX}/100-show_map_3"


def test_prefers_the_newest_timestamp():
    paths = [f"{PREFIX}/100-show_map_3", f"{PREFIX}/200-show_map_3"]
    assert choose_map_path(paths, 3) == f"{PREFIX}/200-show_map_3"


def test_picks_the_requested_map_id():
    paths = [f"{PREFIX}/900-show_map_4", f"{PREFIX}/100-show_map_3"]
    assert choose_map_path(paths, 3) == f"{PREFIX}/100-show_map_3"


def test_falls_back_to_any_map_when_the_id_is_absent():
    paths = [f"{PREFIX}/900-show_map_4"]
    assert choose_map_path(paths, 3) == f"{PREFIX}/900-show_map_4"


def test_layout_is_the_last_resort():
    """lay.bin has geometry but no room names, so it only wins alone."""
    layout = f"{PREFIX}/layout/lay.bin"
    assert choose_map_path([layout], 3) == layout
    assert choose_map_path([layout, f"{PREFIX}/100-show_map_3"], 3) == (
        f"{PREFIX}/100-show_map_3"
    )


def test_no_map_files_at_all():
    assert choose_map_path([f"{PREFIX}/thumbnail.jpg"], 3) is None


# ── End-to-end fetch ────────────────────────────────────────────────


class FakeStream:
    """aiohttp StreamReader stand-in delivering the body in two network reads.

    ``read(n)`` returns only what is buffered (the first read), as aiohttp does.
    """

    def __init__(self, body: bytes, chunks: list[bytes] | None = None) -> None:
        half = len(body) // 2
        self.chunks = chunks if chunks is not None else [body[:half], body[half:]]
        self.consumed = 0

    async def read(self, n: int = -1) -> bytes:
        return self.chunks[0][:n] if n >= 0 else self.chunks[0]

    async def iter_chunked(self, n: int):
        for chunk in self.chunks:
            for start in range(0, len(chunk), n):
                self.consumed += 1
                yield chunk[start : start + n]


def make_storage(*, listing, storage_config, blob=None, status=200, stream=None):
    client = MagicMock()

    async def request(action, data=None, version="1.0"):
        if action == "tuya.m.dev.common.file.list":
            if isinstance(listing, Exception):
                raise listing
            return listing
        if action == "smartlife.m.dev.storage.config.get":
            if isinstance(storage_config, Exception):
                raise storage_config
            return storage_config
        raise AssertionError(f"unexpected action {action}")

    client.request = AsyncMock(side_effect=request)

    response = MagicMock()
    response.status = status
    response.content = stream or FakeStream(blob or b"")
    session = MagicMock()
    session.get = MagicMock(
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=response),
            __aexit__=AsyncMock(return_value=False),
        )
    )
    return TuyaMapStorage(client, session)


def sample_blob() -> bytes:
    return build_blob(
        grid=simple_grid(10, 10, {0: 6, 1: 8}),
        width=10,
        height=10,
        sections=room_name_section({0: "Hallway", 1: "Kitchen"}),
    )


@pytest.mark.asyncio
async def test_fetch_downloads_and_parses_the_map():
    storage = make_storage(
        listing={"datas": [{"path": f"{PREFIX}/100-show_map_3"}]},
        storage_config={"ak": "A", "sk": "S", "bucket": "B", "endpoint": "E"},
        blob=sample_blob(),
    )
    parsed = await storage.async_fetch_map("dev1", 3)
    assert parsed is not None
    assert parsed.room_names == {0: "Hallway", 1: "Kitchen"}


@pytest.mark.asyncio
async def test_fetch_returns_none_when_the_actions_are_not_provisioned():
    """The whole path is optional; the vacuum still works without a map."""
    storage = make_storage(
        listing=RuntimeError("API_OR_API_VERSION_WRONG"),
        storage_config={"ak": "A", "sk": "S", "bucket": "B", "endpoint": "E"},
    )
    assert await storage.async_fetch_map("dev1", 3) is None


@pytest.mark.asyncio
async def test_fetch_returns_none_without_storage_credentials():
    storage = make_storage(
        listing={"datas": [{"path": f"{PREFIX}/100-show_map_3"}]},
        storage_config=RuntimeError("API_OR_API_VERSION_WRONG"),
        blob=sample_blob(),
    )
    assert await storage.async_fetch_map("dev1", 3) is None


@pytest.mark.asyncio
async def test_fetch_returns_none_on_a_download_error():
    storage = make_storage(
        listing={"datas": [{"path": f"{PREFIX}/100-show_map_3"}]},
        storage_config={"ak": "A", "sk": "S", "bucket": "B", "endpoint": "E"},
        blob=sample_blob(),
        status=403,
    )
    assert await storage.async_fetch_map("dev1", 3) is None


@pytest.mark.asyncio
async def test_fetch_returns_none_on_an_unparsable_blob():
    storage = make_storage(
        listing={"datas": [{"path": f"{PREFIX}/100-show_map_3"}]},
        storage_config={"ak": "A", "sk": "S", "bucket": "B", "endpoint": "E"},
        blob=b"this is not a map",
    )
    assert await storage.async_fetch_map("dev1", 3) is None


@pytest.mark.asyncio
async def test_fetch_returns_none_when_nothing_is_stored():
    storage = make_storage(
        listing={"datas": []},
        storage_config={"ak": "A", "sk": "S", "bucket": "B", "endpoint": "E"},
    )
    assert await storage.async_fetch_map("dev1", 3) is None


@pytest.mark.asyncio
async def test_storage_config_is_reused_across_fetches():
    storage = make_storage(
        listing={"datas": [{"path": f"{PREFIX}/100-show_map_3"}]},
        storage_config={"ak": "A", "sk": "S", "bucket": "B", "endpoint": "E"},
        blob=sample_blob(),
    )
    await storage.async_fetch_map("dev1", 3)
    await storage.async_fetch_map("dev1", 3)
    config_calls = [
        call
        for call in storage._client.request.call_args_list
        if call.args[0] == "smartlife.m.dev.storage.config.get"
    ]
    assert len(config_calls) == 1


@pytest.mark.asyncio
async def test_the_working_api_version_is_memoized_per_device():
    """v1.0 is dead on this gateway; only the first fetch should pay for finding that out."""
    storage = make_storage(
        listing={"datas": [{"path": f"{PREFIX}/100-show_map_3"}]},
        storage_config={"ak": "A", "sk": "S", "bucket": "B", "endpoint": "E"},
        blob=sample_blob(),
    )
    inner = storage._client.request.side_effect

    async def only_v2(action, data=None, version="1.0"):
        if version == "1.0":
            raise RuntimeError("API_OR_API_VERSION_WRONG")
        return await inner(action, data, version)

    storage._client.request = AsyncMock(side_effect=only_v2)

    def versions(action):
        return [
            call.kwargs.get("version", "1.0")
            for call in storage._client.request.call_args_list
            if call.args[0] == action
        ]

    assert await storage.async_fetch_map("dev1", 3) is not None
    assert versions("tuya.m.dev.common.file.list") == ["1.0", "2.0"]

    # Second fetch of the same device goes straight to the version that worked.
    assert await storage.async_fetch_map("dev1", 3) is not None
    assert versions("tuya.m.dev.common.file.list") == ["1.0", "2.0", "2.0"]

    # A different device is a different memo, so it probes for itself.
    assert await storage.async_fetch_map("dev2", 3) is not None
    assert versions("tuya.m.dev.common.file.list") == ["1.0", "2.0", "2.0", "1.0", "2.0"]


def test_choose_map_path_prefers_newer_entry_time():
    """Map entry with the newest modification time in listing should win."""
    entries = [
        {
            "extend": "MAP_3",
            "file": f"{PREFIX}/100-show_map_3,{PREFIX}/100-map_3",
            "time": 2000,
        },
        {
            "extend": "MAP_4",
            "file": f"{PREFIX}/200-show_map_4,{PREFIX}/200-map_4",
            "time": 1000,
        },
    ]
    # Even though show_map_4 has a higher filename timestamp (200 > 100),
    # MAP_3 has a newer entry modification time (2000 > 1000).
    chosen = choose_map_path(entries)
    assert chosen == f"{PREFIX}/100-show_map_3"


def test_choose_map_path_filters_by_map_id_with_entries():
    """Specific map_id requested should match entry extend or filename."""
    entries = [
        {
            "extend": "MAP_3",
            "file": f"{PREFIX}/100-show_map_3",
            "time": 2000,
        },
        {
            "extend": "MAP_4",
            "file": f"{PREFIX}/200-show_map_4",
            "time": 1000,
        },
    ]
    assert choose_map_path(entries, 4) == f"{PREFIX}/200-show_map_4"
    assert choose_map_path(entries, 3) == f"{PREFIX}/100-show_map_3"


# ---------------------------------------------------------------------------
# Stored-map freshness token
# ---------------------------------------------------------------------------

def test_map_version_token_changes_when_the_object_is_rewritten():
    """A rewrite moves the entry time and the path stamp; the token follows."""
    before = [{"extend": "MAP_3", "file": f"{PREFIX}/100-show_map_3", "time": 1000}]
    after = [{"extend": "MAP_3", "file": f"{PREFIX}/200-show_map_3", "time": 2000}]
    assert map_version_token(before) != map_version_token(after)


def test_map_version_token_is_stable_for_an_unchanged_listing():
    entries = [{"extend": "MAP_3", "file": f"{PREFIX}/100-show_map_3", "time": 1000}]
    assert map_version_token(entries) == map_version_token(list(entries))


def test_map_version_token_moves_when_only_the_entry_time_moves():
    """The device can rewrite in place; the path stamp alone would miss that."""
    before = [{"extend": "MAP_3", "file": f"{PREFIX}/100-show_map_3", "time": 1000}]
    after = [{"extend": "MAP_3", "file": f"{PREFIX}/100-show_map_3", "time": 2000}]
    assert map_version_token(before) != map_version_token(after)


def test_map_version_token_is_none_without_a_map_object():
    """None means 'unknown' — callers must not read it as 'unchanged'."""
    assert map_version_token([f"{PREFIX}/thumbnail.jpg"]) is None
    assert map_version_token([]) is None


def test_map_version_token_tracks_the_entry_choose_map_path_picks():
    """The token must describe the object that would actually be downloaded."""
    entries = [
        {"extend": "MAP_3", "file": f"{PREFIX}/100-show_map_3", "time": 2000},
        {"extend": "MAP_4", "file": f"{PREFIX}/200-show_map_4", "time": 1000},
    ]
    assert choose_map_path(entries) in map_version_token(entries)


@pytest.mark.asyncio
async def test_async_map_version_does_not_download_the_blob():
    """The cheap half: one list call, no S3 transfer."""
    storage = make_storage(
        listing={"datas": [{"path": f"{PREFIX}/100-show_map_3", "time": 1000}]},
        storage_config={"ak": "A", "sk": "S", "bucket": "B", "endpoint": "E"},
        blob=sample_blob(),
    )
    version = await storage.async_map_version("dev1", 3)
    assert version is not None
    storage._websession.get.assert_not_called()
    # No storage-credential call either: only the listing is needed.
    actions = [c.args[0] for c in storage._client.request.call_args_list]
    assert actions == ["tuya.m.dev.common.file.list"]


@pytest.mark.asyncio
async def test_fetch_records_the_version_it_was_served_from():
    """A successful fetch seeds change-detection with no extra API call."""
    storage = make_storage(
        listing={"datas": [{"path": f"{PREFIX}/100-show_map_3", "time": 1000}]},
        storage_config={"ak": "A", "sk": "S", "bucket": "B", "endpoint": "E"},
        blob=sample_blob(),
    )
    assert storage.last_map_version is None
    assert await storage.async_fetch_map("dev1", 3) is not None
    assert storage.last_map_version is not None
    # And it matches what a standalone check would report for the same listing.
    assert storage.last_map_version == await storage.async_map_version("dev1", 3)


@pytest.mark.asyncio
async def test_fetch_refuses_an_oversized_map_object():
    """A real map blob is a few KB; an oversized object feeds a decompressor."""
    storage = make_storage(
        listing={"datas": [{"path": f"{PREFIX}/100-show_map_3"}]},
        storage_config={"ak": "A", "sk": "S", "bucket": "B", "endpoint": "E"},
        blob=b"\x00" * (_MAX_MAP_BLOB_BYTES + 1),
    )
    assert await storage.async_fetch_map("dev1", 3) is None


@pytest.mark.asyncio
async def test_fetch_stops_reading_once_the_cap_is_passed(monkeypatch):
    """The body is not buffered beyond the cap."""
    monkeypatch.setattr(tuya_storage, "_MAX_MAP_BLOB_BYTES", 10)
    stream = FakeStream(b"", chunks=[b"\x00" * 8] * 100)
    storage = make_storage(
        listing={"datas": [{"path": f"{PREFIX}/100-show_map_3"}]},
        storage_config={"ak": "A", "sk": "S", "bucket": "B", "endpoint": "E"},
        stream=stream,
    )
    assert await storage.async_fetch_map("dev1", 3) is None
    assert stream.consumed == 2


@pytest.mark.asyncio
async def test_fetch_parses_through_the_executor_when_one_is_supplied():
    """parse_map_blob must not run on the event loop."""
    used = {}

    async def fake_executor(fn, *args):
        used["called"] = True
        return fn(*args)

    storage = make_storage(
        listing={"datas": [{"path": f"{PREFIX}/100-show_map_3"}]},
        storage_config={"ak": "A", "sk": "S", "bucket": "B", "endpoint": "E"},
        blob=sample_blob(),
    )
    storage._run_in_executor = fake_executor
    assert await storage.async_fetch_map("dev1", 3) is not None
    assert used.get("called") is True
