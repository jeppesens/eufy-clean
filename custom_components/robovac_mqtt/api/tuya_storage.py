"""Fetch a legacy device's map file from Tuya cloud storage.

No datapoint carries the map: ``tuya.m.dev.common.file.list`` names the stored
objects, ``smartlife.m.dev.storage.config.get`` returns short-lived S3
credentials, then a SigV4 presigned GET fetches the object. Both are
undocumented with unstable field names, so lookups accept every alias and the
path degrades to "no map".
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import aiohttp

from .tuya_cloud import TuyaCallProbe
from .tuya_map import TuyaMap, TuyaMapError, parse_map_blob

_LOGGER = logging.getLogger(__name__)

# Real map objects are a few KB; 8 MiB is ample headroom.
_MAX_MAP_BLOB_BYTES = 8 * 1024 * 1024
_READ_CHUNK_BYTES = 65536
_DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=30)

# The gateway accepts only one of these per device, so both are probed.
_API_VERSIONS = ("1.0", "2.0")

# ``show_map`` is the rendered snapshot, ``map`` the clean-record copy.
_MAP_FILE_RE = re.compile(r"(?:^|/)(\d+)-(show_map|map)_(\d+)$")
_EXTEND_MAP_RE = re.compile(r"MAP_(\d+)", re.IGNORECASE)
_LAYOUT_SUFFIX = "layout/lay.bin"

# The SDK renames some of these on the way through; accept every spelling.
_ALIASES = {
    "access_key": ("ak", "accessKey", "accessKeyId", "accessId"),
    "secret_key": ("sk", "secretKey", "accessKeySecret"),
    "token": ("token", "securityToken", "sessionToken", "stsToken"),
    "bucket": ("bucket", "bucketName", "bucketname"),
    "endpoint": ("endpoint", "endPoint", "host"),
    "region": ("region", "regionId"),
    "path": ("path", "filePath", "key", "objectKey", "url", "fileUrl", "name", "file"),
}


def _pick(source: Any, field: str) -> str:
    """Read one logical field from a response dict, trying known aliases."""
    if not isinstance(source, dict):
        return ""
    for alias in _ALIASES[field]:
        value = source.get(alias)
        if isinstance(value, str) and value:
            return value
    return ""


@dataclass(frozen=True)
class StorageConfig:
    """Short-lived S3 credentials for one device's object store."""

    access_key: str
    secret_key: str
    token: str
    bucket: str
    endpoint: str
    region: str

    @property
    def valid(self) -> bool:
        return bool(
            self.access_key and self.secret_key and self.bucket and self.endpoint
        )

    @classmethod
    def from_response(cls, payload: Any) -> StorageConfig | None:
        if not isinstance(payload, dict):
            return None
        # Some responses nest the credentials one level down.
        for candidate in (payload, payload.get("data"), payload.get("config"), payload.get("result")):
            if not isinstance(candidate, dict):
                continue
            config = cls(
                access_key=_pick(candidate, "access_key"),
                secret_key=_pick(candidate, "secret_key"),
                token=_pick(candidate, "token"),
                bucket=_pick(candidate, "bucket"),
                endpoint=_pick(candidate, "endpoint"),
                # Tuya sets region to the endpoint host, not an AWS region.
                region=_pick(candidate, "region") or _pick(candidate, "endpoint"),
            )
            if config.valid:
                return config
        return None


def _sigv4_presign(config: StorageConfig, path: str, expires: int = 3600) -> str:
    """Build a SigV4 presigned GET URL: ``service=s3``, endpoint host used
    verbatim as the region."""
    host = f"{config.bucket}.{config.endpoint}"
    canonical_uri = "/" + "/".join(
        quote(segment, safe="~") for segment in path.strip("/").split("/")
    )

    now = datetime.now(UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    scope = f"{date_stamp}/{config.region}/s3/aws4_request"

    params = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{config.access_key}/{scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(expires),
        "X-Amz-SignedHeaders": "host",
    }
    if config.token:
        params["X-Amz-Security-Token"] = config.token

    canonical_query = "&".join(
        f"{quote(key, safe='~')}={quote(params[key], safe='~')}"
        for key in sorted(params)
    )
    canonical_request = "\n".join(
        [
            "GET",
            canonical_uri,
            canonical_query,
            f"host:{host}\n",
            "host",
            "UNSIGNED-PAYLOAD",
        ]
    )
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )

    key = f"AWS4{config.secret_key}".encode()
    for part in (date_stamp, config.region, "s3", "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()

    return (
        f"https://{host}{canonical_uri}?{canonical_query}"
        f"&X-Amz-Signature={signature}"
    )


def _file_entries(listing: Any) -> list[Any]:
    """Extract entry dicts or path strings from a file-list response."""
    if isinstance(listing, list):
        return listing
    if isinstance(listing, dict):
        for key in ("datas", "data", "list", "files", "result"):
            value = listing.get(key)
            if isinstance(value, list):
                return value
    return []


def _scan_map_entries(
    items: list[Any], map_id: int | None = None
) -> tuple[tuple[int, int, str] | None, str | None]:
    """Rank a file listing into ``(best, layout)``.

    ``best`` is ``(effective_time, kind_rank, path)``, ``layout`` the last
    resort. One ranking for both public helpers.
    """
    best: tuple[int, int, str] | None = None
    layout: str | None = None

    for item in items:
        entry_time = 0
        paths: list[str] = []
        item_map_id: int | None = None

        if isinstance(item, dict):
            entry_time = int(item.get("time") or 0)
            extend = item.get("extend") or ""
            if m := _EXTEND_MAP_RE.search(str(extend)):
                item_map_id = int(m.group(1))
            raw_file = item.get("file") or item.get("path") or _pick(item, "path")
            if isinstance(raw_file, str):
                paths = [p.strip() for p in raw_file.split(",") if p.strip()]
            elif isinstance(raw_file, list):
                paths = [str(p) for p in raw_file]
        elif isinstance(item, str):
            paths = [item]

        for path in paths:
            if path.endswith(_LAYOUT_SUFFIX):
                layout = path
                continue
            match = _MAP_FILE_RE.search(path)
            if not match:
                continue
            path_ts, kind, found_id = match.groups()
            effective_map_id = item_map_id if item_map_id is not None else int(found_id)
            effective_time = entry_time if entry_time > 0 else int(path_ts)

            if map_id is not None and effective_map_id != map_id:
                continue

            rank = (effective_time, 1 if kind == "show_map" else 0, path)
            if best is None or rank > best:
                best = rank

    return best, layout


def choose_map_path(items: list[Any], map_id: int | None = None) -> str | None:
    """Pick the object most likely to hold a named room list.

    Most recent entry time (or matching map_id) wins; ``lay.bin`` is geometry
    only, the last resort.
    """
    best, layout = _scan_map_entries(items, map_id)
    if best is not None:
        return best[2]
    if map_id is not None:
        return choose_map_path(items, None) or layout
    return layout


def map_version_token(items: list[Any], map_id: int | None = None) -> str | None:
    """Build a cheap "has the stored map changed?" token for a file listing.

    Combines listing ``time`` with the path timestamp, so a rewrite is caught
    when either is stuck. None is "unknown", never "unchanged".
    """
    best, _layout = _scan_map_entries(items, map_id)
    if best is None:
        return None
    return f"{best[0]}:{best[2]}"


class TuyaMapStorage:
    """Downloads and parses a legacy device's map from Tuya cloud storage."""

    def __init__(
        self,
        client: Any,
        websession: aiohttp.ClientSession,
        run_in_executor: Any | None = None,
    ) -> None:
        self._client = client
        self._websession = websession
        # Awaitable ``fn(callable, *args)``; optional, for use outside hass.
        self._run_in_executor = run_in_executor
        self._config: StorageConfig | None = None
        self._config_expires_at: float = 0.0
        # Keyed per device: one instance can serve several devices.
        self._probe = TuyaCallProbe("Tuya storage")
        # Listing version the last fetch was served from, for change detection.
        self.last_map_version: str | None = None

    def _invalidate_config(self) -> None:
        """Drop the cached S3 credentials so the next fetch refreshes them."""
        self._config = None
        self._config_expires_at = 0.0

    async def _get_config(self, device_id: str | None = None) -> StorageConfig | None:
        """Fetch (and briefly cache) the S3 credentials."""
        if self._config is not None and time.monotonic() < self._config_expires_at:
            return self._config
        payload_data = {"devId": device_id, "type": "Common"} if device_id else None

        async def attempt(version: str) -> StorageConfig | None:
            payload = await self._client.request(
                "smartlife.m.dev.storage.config.get",
                data=payload_data,
                version=version,
            )
            config = StorageConfig.from_response(payload)
            if config is None:
                _LOGGER.debug("Storage config (v%s) had no usable credentials", version)
            return config

        # Any failure just means "no map"; the probe already logged it.
        config, _ = await self._probe.run(
            f"storage.config:{device_id}", _API_VERSIONS, attempt
        )
        if config is not None:
            self._config = config
            self._config_expires_at = time.monotonic() + 1800
        return config

    async def _list_files(self, device_id: str) -> list[Any]:
        async def attempt(version: str) -> list[Any] | None:
            listing = await self._client.request(
                "tuya.m.dev.common.file.list",
                data={"devId": device_id, "offset": 0, "limit": 8, "fileType": "collect_recode"},
                version=version,
            )
            return _file_entries(listing) or None

        entries, _ = await self._probe.run(
            f"file.list:{device_id}", _API_VERSIONS, attempt
        )
        return entries or []

    async def async_map_version(
        self, device_id: str, map_id: int | None = None
    ) -> str | None:
        """Return the stored-map version token WITHOUT downloading the blob.

        None means "unknown" (empty listing or no map object), not "unchanged".
        """
        entries = await self._list_files(device_id)
        if not entries:
            return None
        return map_version_token(entries, map_id)

    async def async_fetch_map(
        self, device_id: str, map_id: int | None = None
    ) -> TuyaMap | None:
        """Download and parse the device's current map, or None."""
        entries = await self._list_files(device_id)
        if not entries:
            _LOGGER.debug("No stored files listed for %s", device_id)
            return None

        path = choose_map_path(entries, map_id)
        if path is None:
            _LOGGER.debug("No map file among %d stored entries for %s", len(entries), device_id)
            return None

        config = await self._get_config(device_id)
        if config is None:
            _LOGGER.debug("No storage credentials; cannot download %s", path)
            return None

        url = _sigv4_presign(config, path)
        try:
            async with self._websession.get(url, timeout=_DOWNLOAD_TIMEOUT) as resp:
                if resp.status != 200:
                    _LOGGER.debug(
                        "Map download for %s returned HTTP %s", device_id, resp.status
                    )
                    # Most likely the cached STS token lapsed (it is cached
                    # blind to its TTL); drop it so the next attempt refetches.
                    self._invalidate_config()
                    return None
                # Feeds a decompressor: uncapped, this is a memory-exhaustion
                # vector before parsing even begins.
                body = bytearray()
                async for chunk in resp.content.iter_chunked(_READ_CHUNK_BYTES):
                    body += chunk
                    if len(body) > _MAX_MAP_BLOB_BYTES:
                        _LOGGER.debug(
                            "Map object for %s exceeds %d bytes; refusing",
                            device_id, _MAX_MAP_BLOB_BYTES,
                        )
                        return None
                blob = bytes(body)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Map download for %s failed: %s", device_id, err)
            return None

        try:
            # Grid-sized pure Python plus a decompressor: not on the loop.
            if self._run_in_executor is not None:
                parsed = await self._run_in_executor(parse_map_blob, blob)
            else:
                parsed = parse_map_blob(blob)
        except TuyaMapError as err:
            _LOGGER.debug("Map blob for %s is unparsable: %s", device_id, err)
            return None

        # Off the listing already in hand: no second file-list call.
        self.last_map_version = map_version_token(entries, map_id)
        _LOGGER.debug(
            "Fetched map %d for %s from %s: %d rooms",
            parsed.map_id, device_id, path, len(parsed.rooms),
        )
        return parsed
