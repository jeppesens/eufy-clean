"""Tuya Cloud API client for legacy Eufy devices.

Ported from the upstream martijnpoppen/eufy-clean TypeScript SDK
(src/lib/TuyaCloud.js + src/api/TuyaCloudApi.ts).

Uses HMAC-SHA256 request signing and RSA-encrypted loginEx flow.
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
from typing import Any

import aiohttp

from ..const import (
    TUYA_API_ET_VERSION,
    TUYA_CERT_SIGN,
    TUYA_CLIENT_ID,
    TUYA_REGIONS,
    TUYA_SECRET,
    TUYA_SECRET2,
)

_LOGGER = logging.getLogger(__name__)

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)

# Fields included in the HMAC signature (order matters for sorting)
_SIGN_FIELDS = frozenset({
    "a", "v", "lat", "lon", "lang", "deviceId", "imei", "imsi",
    "appVersion", "ttid", "isH5", "h5Token", "os", "clientId",
    "postData", "time", "requestId", "n4h5", "sid", "sp", "et",
})

# AES key/iv used in loginEx password derivation (hardcoded in upstream)
_AES_KEY = bytes([36, 78, 109, 138, 86, 172, 135, 145, 36, 67, 45, 139, 108, 188, 162, 196])
_AES_IV = bytes([119, 36, 86, 242, 167, 102, 76, 243, 57, 44, 53, 151, 233, 62, 87, 71])


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
    """MD5 + character shuffle used by Tuya for postData signing.

    Rearranges MD5 hex digest: [8:16] + [0:8] + [24:32] + [16:24]
    """
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
        self.endpoint = TUYA_REGIONS.get(region, TUYA_REGIONS["EU"])
        self.sid: str | None = None
        # Match upstream JS: randomize('a0', 44) — 44-char lowercase alphanumeric
        self._device_id = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=44)
        )
        self._websession = websession
        self._hmac_key = f"{TUYA_CERT_SIGN}_{TUYA_SECRET2}_{TUYA_SECRET}"

    async def login(self, eufy_user_id: str) -> str:
        """Login via Tuya's loginEx flow using the Eufy user_id.

        1. Request a token + RSA public key
        2. Encrypt password using AES + RSA
        3. Authenticate and get session ID
        """
        uid = f"eh-{eufy_user_id}"
        _LOGGER.debug("Tuya login starting for region %s, uid=%s", self.region, uid)

        # Step 1: Get token and RSA public key
        token_result = await self.request(
            "tuya.m.user.uid.token.create",
            data={"countryCode": self.region, "uid": uid},
            requires_sid=False,
        )

        public_key_n = token_result["publicKey"]
        exponent = int(token_result["exponent"])
        token = token_result["token"]
        _LOGGER.debug(
            "Tuya token received: publicKey length=%d, first8=%s, last8=%s, "
            "exponent=%d, is_hex=%s",
            len(public_key_n), public_key_n[:8], public_key_n[-8:],
            exponent, _is_hex(public_key_n),
        )

        # Step 2: Encrypt password
        encrypted_pass = _encrypt_password(uid, public_key_n, exponent)

        # Step 3: Login with encrypted password
        login_result = await self.request(
            "tuya.m.user.uid.password.login",
            data={
                "countryCode": self.region,
                "uid": uid,
                "createGroup": True,
                "passwd": encrypted_pass,
                "ifencrypt": 1,
                "options": {"group": 1},
                "token": token,
            },
            requires_sid=False,
        )

        # Handle region redirect
        domain = login_result.get("domain", {})
        mobile_api_url = domain.get("mobileApiUrl")
        if mobile_api_url and not self.endpoint.startswith(mobile_api_url):
            self.endpoint = mobile_api_url + "/api.json"
            self.region = domain.get("regionCode", self.region)
            _LOGGER.debug("Tuya redirected to region %s: %s", self.region, self.endpoint)

        self.sid = login_result["sid"]
        _LOGGER.debug("Tuya login successful, sid obtained for region %s", self.region)
        return self.sid

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

        # Sign the request
        params["sign"] = self._sign(params)

        session = self._websession
        async with session.get(
            self.endpoint, params=params, timeout=_REQUEST_TIMEOUT
        ) as resp:
            _LOGGER.debug("Tuya request actual URL: %s", resp.url)
            body = await resp.json(content_type=None)

        if body.get("success") is False:
            error_code = body.get("errorCode", "UNKNOWN")
            error_msg = body.get("errorMsg", "Unknown error")
            _LOGGER.debug("Tuya API error: action=%s, code=%s, msg=%s", action, error_code, error_msg)
            raise TuyaCloudError(error_code, error_msg)

        _LOGGER.debug("Tuya request succeeded: action=%s", action)
        return body.get("result")

    async def get_device_list(self) -> list[dict[str, Any]]:
        """Fetch all devices from Tuya Cloud (groups + shared)."""
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
        return all_devices

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
        _LOGGER.debug("Tuya send_command to %s: %s", device_id, dps)
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
        _LOGGER.debug("Tuya sign string: %s", sign_str)
        return _hmac_sign(self._hmac_key, sign_str)


def _encrypt_password(uid: str, public_key_n: str, exponent: int) -> str:
    """Encrypt password for Tuya loginEx using AES-CBC + RSA.

    1. AES-128-CBC encrypt the uid (zero-padded to 16-byte boundary)
    2. MD5 the uppercase hex of the encrypted uid
    3. RSA encrypt that MD5 with the server's public key
    """
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend

    # AES-128-CBC encrypt uid
    padded_len = 16 * math.ceil(len(uid) / 16)
    padded_uid = uid.rjust(padded_len, "0")

    cipher = Cipher(
        algorithms.AES(_AES_KEY),
        modes.CBC(_AES_IV),
        backend=default_backend(),
    )
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(padded_uid.encode()) + encryptor.finalize()
    encrypted_hex = encrypted.hex().upper()

    # MD5 the encrypted hex
    password_md5 = _md5(encrypted_hex)

    # RSA encrypt with public key (no padding, raw RSA)
    is_hex = _is_hex(public_key_n)
    n = int(public_key_n, 16) if is_hex else int(public_key_n)
    e = exponent

    # Raw RSA: m^e mod n
    m = int.from_bytes(password_md5.encode(), "big")
    c = pow(m, e, n)

    # Convert to hex, zero-padded to key size.
    # Use ceil(hex_len / 2) to: (a) preserve leading zeros that n.bit_length()
    # would drop, and (b) handle odd-length hex strings (e.g. 309-char keys
    # from real Tuya servers → 155 bytes, not 154).
    key_size = (len(public_key_n) + 1) // 2 if is_hex else (n.bit_length() + 7) // 8
    result = c.to_bytes(key_size, "big").hex()

    _LOGGER.debug(
        "Password encryption: uid_len=%d, padded_len=%d, aes_hex_len=%d, "
        "md5_len=%d, n_bits=%d, key_size=%d, result_len=%d",
        len(uid), padded_len, len(encrypted_hex),
        len(password_md5), n.bit_length(), key_size, len(result),
    )
    return result


def _is_hex(s: str) -> bool:
    """Check if a string is a hex number."""
    try:
        int(s, 16)
        return True
    except ValueError:
        return False
