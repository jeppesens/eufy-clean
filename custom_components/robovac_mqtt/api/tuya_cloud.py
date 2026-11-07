"""Tuya Cloud API client for legacy Eufy devices.

Ported from the upstream martijnpoppen/eufy-clean TypeScript SDK; HMAC-SHA256
request signing plus the RSA-encrypted loginEx flow.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import random
import string
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, TypeVar

import aiohttp
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from ..const import (
    TUYA_API_ET_VERSION,
    TUYA_CERT_SIGN,
    TUYA_CLIENT_ID,
    TUYA_REGIONS,
    TUYA_SECRET,
    TUYA_SECRET2,
)

_LOGGER = logging.getLogger(__name__)

# Just under the 30 s poll, so N devices collapse to one fetch per round.
_DEVICE_LIST_TTL = 25.0
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)

# Fields included in the HMAC signature; sorted before joining.
_SIGN_FIELDS = frozenset({
    "a", "v", "lat", "lon", "lang", "deviceId", "imei", "imsi",
    "appVersion", "ttid", "isH5", "h5Token", "os", "clientId",
    "postData", "time", "requestId", "n4h5", "sid", "sp", "et",
})

# AES key/iv for the loginEx password derivation, as upstream hardcodes them.
_AES_KEY = bytes([36, 78, 109, 138, 86, 172, 135, 145, 36, 67, 45, 139, 108, 188, 162, 196])
_AES_IV = bytes([119, 36, 86, 242, 167, 102, 76, 243, 57, 44, 53, 151, 233, 62, 87, 71])


def parse_device_schema(raw_schema: Any) -> dict[str, dict[str, Any]]:
    """Normalise a Tuya ``schema`` field into ``{dps_id: descriptor}``.

    Empty dict when missing or unparsable; callers then use their defaults.
    """
    if isinstance(raw_schema, str):
        try:
            raw_schema = json.loads(raw_schema)
        except (ValueError, TypeError):
            _LOGGER.debug("Tuya schema is not valid JSON; ignoring")
            return {}
    if not isinstance(raw_schema, list):
        return {}

    schema: dict[str, dict[str, Any]] = {}
    for entry in raw_schema:
        if not isinstance(entry, dict) or entry.get("id") is None:
            continue
        prop = entry.get("property") or {}
        schema[str(entry["id"])] = {
            "code": entry.get("code", ""),
            "mode": entry.get("mode", ""),
            "type": prop.get("type", ""),
            "range": list(prop.get("range", [])),
            "unit": prop.get("unit", ""),
            "min": prop.get("min"),
            "max": prop.get("max"),
            "maxlen": prop.get("maxlen"),
        }
    return schema


_C = TypeVar("_C")


class TuyaCallProbe:
    """Memoize which undocumented call shape a Tuya action answered on.

    A memo that stops working is dropped and the probe re-runs, so it can
    never permanently break the call. ``key`` must also name the device when
    one probe serves several.
    """

    def __init__(self, label: str) -> None:
        self._label = label
        self._winners: dict[str, Any] = {}

    def forget(self, key: str) -> None:
        """Drop the memoized combination for ``key``, if there is one."""
        if self._winners.pop(key, None) is not None:
            _LOGGER.debug("%s: %s memo invalidated", self._label, key)

    async def run(
        self,
        key: str,
        candidates: Iterable[_C],
        attempt: Callable[[_C], Awaitable[Any]],
    ) -> tuple[Any, Exception | None]:
        """Await ``attempt(candidate)`` until one returns non-None; returns
        ``(result, last_error)``, result None when nothing worked."""
        last_error: Exception | None = None

        memo = self._winners.get(key)
        if memo is not None:
            result, last_error = await self._attempt(key, memo, attempt)
            if result is not None:
                return result, None
            self.forget(key)

        for candidate in candidates:
            result, err = await self._attempt(key, candidate, attempt)
            if err is not None:
                last_error = err
            if result is not None:
                self._winners[key] = candidate
                _LOGGER.debug("%s: %s memoized %r", self._label, key, candidate)
                return result, last_error
        return None, last_error

    async def _attempt(
        self, key: str, candidate: _C, attempt: Callable[[_C], Awaitable[Any]]
    ) -> tuple[Any, Exception | None]:
        try:
            return await attempt(candidate), None
        except Exception as err:  # noqa: BLE001 - any failure means "try the next"
            _LOGGER.debug("%s: %s via %r failed: %s", self._label, key, candidate, err)
            return None, err


class TuyaCloudError(Exception):
    """Tuya Cloud API error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"Tuya API error {code}: {message}")
        self.code = code
        self.message = message


def _md5(data: str) -> str:
    """MD5 hash a string, return hex digest."""
    return hashlib.md5(data.encode()).hexdigest()


def _mobile_hash(data: str) -> str:
    """MD5 plus the hex-digest shuffle Tuya uses for postData signing."""
    h = _md5(data)
    return h[8:16] + h[0:8] + h[24:32] + h[16:24]


def _hmac_sign(key: str, message: str) -> str:
    """HMAC-SHA256 sign a message."""
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()


class TuyaCloudClient:
    """Async Tuya Cloud API client."""

    def __init__(
        self,
        region: str,
        websession: aiohttp.ClientSession,
    ) -> None:
        self.region = region
        # The login countryCode; a redirect rewrites region, never this.
        self._country_code = region
        self.endpoint = TUYA_REGIONS.get(region, TUYA_REGIONS["EU"])
        self.sid: str | None = None
        # 44-char lowercase alphanumeric, as upstream's randomize('a0', 44).
        self._device_id = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=44)
        )
        self._websession = websession
        self._hmac_key = f"{TUYA_CERT_SIGN}_{TUYA_SECRET2}_{TUYA_SECRET}"
        # Short-lived memo for the account-wide device list; see get_device_list.
        self._device_list_cache: list[dict[str, Any]] | None = None
        self._device_list_cached_at: float = 0.0

    async def login(self, eufy_user_id: str) -> str:
        """Log in via Tuya's loginEx flow using the Eufy user_id.

        Safe to repeat on the same instance: it keeps the device id and the
        probed countryCode, and replaces ``sid``.
        """
        uid = f"eh-{eufy_user_id}"
        # The uid alone is enough to log in (passwd is derived from it); never log it.
        _LOGGER.debug("Tuya login starting for region %s", self.region)

        token_result = await self.request(
            "tuya.m.user.uid.token.create",
            data={"countryCode": self._country_code, "uid": uid},
            requires_sid=False,
        )
        if not isinstance(token_result, dict) or not all(
            token_result.get(k) for k in ("publicKey", "exponent", "token")
        ):
            raise TuyaCloudError("BAD_RESPONSE", "token.create returned no token")

        public_key_n = token_result["publicKey"]
        exponent = int(token_result["exponent"])
        token = token_result["token"]
        _LOGGER.debug(
            "Tuya token received: publicKey length=%d, first8=%s, last8=%s, "
            "exponent=%d, is_hex=%s",
            len(public_key_n), public_key_n[:8], public_key_n[-8:],
            exponent, _is_hex(public_key_n),
        )

        encrypted_pass = _encrypt_password(uid, public_key_n, exponent)

        login_result = await self.request(
            "tuya.m.user.uid.password.login",
            data={
                "countryCode": self._country_code,
                "uid": uid,
                "createGroup": True,
                "passwd": encrypted_pass,
                "ifencrypt": 1,
                "options": {"group": 1},
                "token": token,
            },
            requires_sid=False,
        )
        if not isinstance(login_result, dict) or not login_result.get("sid"):
            raise TuyaCloudError("BAD_RESPONSE", "password.login returned no sid")

        domain = login_result.get("domain") or {}
        mobile_api_url = domain.get("mobileApiUrl")
        if mobile_api_url and not self.endpoint.startswith(mobile_api_url):
            self.endpoint = mobile_api_url + "/api.json"
            self.region = domain.get("regionCode", self.region)
            _LOGGER.debug("Tuya redirected to region %s: %s", self.region, self.endpoint)

        self.sid = login_result["sid"]
        # A new session may see a different account scope; drop the memo.
        self._device_list_cache = None
        _LOGGER.debug("Tuya login successful, sid obtained for region %s", self.region)
        return login_result["sid"]

    async def request(
        self,
        action: str,
        data: dict[str, Any] | None = None,
        *,
        version: str = "1.0",
        requires_sid: bool = True,
        gid: str | None = None,
    ) -> Any:
        """Make a signed request to the Tuya Cloud API."""
        _LOGGER.debug("Tuya request: action=%s, requires_sid=%s", action, requires_sid)
        if requires_sid and not self.sid:
            raise TuyaCloudError("NO_SID", "Must call login() first")

        now = int(time.time())

        params: dict[str, Any] = {
            "a": action,
            "deviceId": self._device_id,
            "sdkVersion": "3.0.0cAnker",
            "os": "Android",
            "lang": "en",
            "appVersion": "3.8.5",
            "v": version,
            "clientId": TUYA_CLIENT_ID,
            "time": now,
            "et": TUYA_API_ET_VERSION,
            "ttid": "android",
            "appRnVersion": "5.11",
            "platform": "Android",
            "requestId": str(uuid.uuid4()),
        }

        if data is not None:
            params["postData"] = json.dumps(data, separators=(",", ":"))

        if gid is not None:
            params["gid"] = gid

        if requires_sid:
            params["sid"] = self.sid

        params["sign"] = self._sign(params)

        # Query parameters and signing inputs contain credentials; never log them.
        session = self._websession
        async with session.get(
            self.endpoint, params=params, timeout=_REQUEST_TIMEOUT
        ) as resp:
            body = await resp.json(content_type=None)

        if not isinstance(body, dict):
            raise TuyaCloudError("BAD_RESPONSE", f"{action}: non-object response")
        if body.get("success") is False:
            error_code = body.get("errorCode", "UNKNOWN")
            error_msg = body.get("errorMsg", "Unknown error")
            _LOGGER.debug("Tuya API error: action=%s, code=%s, msg=%s", action, error_code, error_msg)
            raise TuyaCloudError(error_code, error_msg)

        _LOGGER.debug("Tuya request succeeded: action=%s", action)
        return body.get("result")

    async def get_device_list(self, force: bool = False) -> list[dict[str, Any]]:
        """Fetch all devices from Tuya Cloud (groups + shared).

        Three sequential calls, so memoized; ``force=True`` bypasses.
        """
        now = time.monotonic()
        if (
            not force
            and self._device_list_cache is not None
            and now - self._device_list_cached_at < _DEVICE_LIST_TTL
        ):
            return self._device_list_cache

        groups = await self.request("tuya.m.location.list")
        all_devices: list[dict[str, Any]] = []

        for group in groups or []:
            gid = group.get("groupId")
            if not gid:
                continue

            devices = await self.request(
                "tuya.m.my.group.device.list", gid=gid
            )
            all_devices.extend(devices or [])
            _LOGGER.debug("Tuya group %s: %d devices", gid, len(devices or []))
            break  # Upstream only processes first group

        # Shared devices are account-level, not group-scoped
        shared = await self.request("tuya.m.my.shared.device.list")
        all_devices.extend(shared or [])

        _LOGGER.debug("Tuya get_device_list: total %d devices", len(all_devices))
        self._device_list_cache = all_devices
        self._device_list_cached_at = now
        return all_devices

    async def get_device_schema(self, device_id: str) -> dict[str, dict[str, Any]]:
        """Fetch a device's DPS schema; only the per-device record has it.

        Empty dict on failure: callers fall back, they do not lose the device.
        """
        try:
            detail = await self.request(
                "tuya.m.device.get", data={"devId": device_id}
            )
        except Exception as e:  # noqa: BLE001 - schema is best-effort
            _LOGGER.debug("Tuya schema fetch failed for %s: %s", device_id, e)
            return {}
        if not isinstance(detail, dict):
            return {}
        schema = parse_device_schema(detail.get("schema"))
        _LOGGER.debug(
            "Tuya schema for %s: %d DPS described", device_id, len(schema)
        )
        return schema

    async def get_device(self, device_id: str) -> dict[str, Any] | None:
        """Poll a single device's state (DPS) from Tuya Cloud."""
        devices = await self.get_device_list()
        for device in devices:
            if device.get("devId") == device_id:
                dps = device.get("dps", {})
                _LOGGER.debug("Tuya get_device %s: found, %d DPS keys", device_id, len(dps))
                return dps
        _LOGGER.debug("Tuya get_device %s: not found in %d devices", device_id, len(devices))
        return None

    async def send_command(
        self, device_id: str, dps: dict[str, Any]
    ) -> None:
        """Send a DPS command to a device via Tuya Cloud."""
        # Keys only: DPS 124 values carry room names and zone geometry.
        _LOGGER.debug("Tuya send_command to %s: DPS %s", device_id, sorted(dps))
        await self.request(
            "tuya.m.device.dp.publish",
            data={"dps": dps, "devId": device_id, "gwId": device_id},
        )

    def _sign(self, params: dict[str, Any]) -> str:
        """Build HMAC-SHA256 signature for request parameters."""
        sorted_keys = sorted(params.keys())
        parts: list[str] = []

        for key in sorted_keys:
            if key not in _SIGN_FIELDS or key == "sign":
                continue
            value = params.get(key)
            if value is None or value == "":
                continue

            if key == "postData":
                parts.append(f"{key}={_mobile_hash(str(value))}")
            else:
                parts.append(f"{key}={value}")

        sign_str = "||".join(parts)
        return _hmac_sign(self._hmac_key, sign_str)


def uid_password_md5(uid: str) -> str:
    """The uid-derived login secret: MD5 hex of the AES-128-CBC'd, zero-padded uid."""
    padded_len = 16 * math.ceil(len(uid) / 16)
    padded_uid = uid.rjust(padded_len, "0")

    cipher = Cipher(
        algorithms.AES(_AES_KEY),
        modes.CBC(_AES_IV),
        backend=default_backend(),
    )
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(padded_uid.encode()) + encryptor.finalize()
    return _md5(encrypted.hex().upper())


def _encrypt_password(uid: str, public_key_n: str, exponent: int) -> str:
    """Encrypt the loginEx password: raw RSA of uid_password_md5 with the
    server's public key."""
    password_md5 = uid_password_md5(uid)

    # Raw RSA, no padding: m^e mod n.
    is_hex = _is_hex(public_key_n)
    n = int(public_key_n, 16) if is_hex else int(public_key_n)
    e = exponent

    m = int.from_bytes(password_md5.encode(), "big")
    c = pow(m, e, n)

    # Zero-pad to key size; the hex length preserves upstream's leading zeros.
    if is_hex:
        key_size = len(public_key_n) // 2
    else:
        key_size = (n.bit_length() + 7) // 8

    return c.to_bytes(key_size, "big").hex()


def _is_hex(s: str) -> bool:
    """Is this a hex number? Pure-decimal strings are not."""
    return bool(set(s.lower()) & set('abcdef'))
