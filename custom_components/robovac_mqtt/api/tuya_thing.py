"""Tuya Thing SDK (et=3) transport for legacy Eufy devices whose map/room data lives in Tuya cloud."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import random
import string
import time
import uuid
from collections.abc import Callable
from typing import Any

import aiohttp
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import load_der_public_key

from ..const import (
    TUYA_REGIONS,
    TUYA_THING_CHKEY,
    TUYA_THING_CLIENT_ID,
    TUYA_THING_SALT,
)
from .tuya_cloud import _mobile_hash, uid_password_md5

_LOGGER = logging.getLogger(__name__)

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)

# Params sent on the wire but not hashed into `sign`. Two non-obvious cases:
# "gid" is sent unsigned (listed), "sp" IS signed (deliberately not listed).
_EXCLUDE_FIELDS = frozenset({
    "bizData",
    "channel",
    "cp",
    "deviceCoreVersion",
    "gid",
    "osSystem",
    "platform",
    "sdkVersion",
    "timeZoneId",
    "sign",
    "_sign",
    "nd",
})


class TuyaThingError(Exception):
    """Tuya Thing API error."""

    def __init__(self, code: str | int, message: str) -> None:
        super().__init__(f"Tuya Thing API error {code}: {message}")
        self.code = code
        self.message = message


# Gateway codes meaning the session was rejected (expired sid, or a signature
# over one): the only errors a fresh login can fix, hence the only retryable ones.
_SESSION_ERROR_CODES = frozenset(
    {
        "SIGN_INVALID",
        "SESSION_INVALID",
        "USER_SESSION_INVALID",
        "USER_SESSION_EXPIRE",
        "NOT_EXISTS_SESSION",
        "TOKEN_INVALID",
        "PERMISSION_DENIED",
    }
)


def is_session_error(err: Exception) -> bool:
    """Does this Tuya error say the session, rather than the request, was rejected?

    Reads the ``code`` and ``message`` attributes that both TuyaThingError and
    TuyaCloudError carry.
    """
    code = str(getattr(err, "code", "")).upper()
    if code in _SESSION_ERROR_CODES:
        return True
    # gateways are inconsistent about the code; fall back to the message text
    text = f"{code} {getattr(err, 'message', '')}".lower()
    return "session" in text or "sign invalid" in text or "token" in text


def _get_prelogin_key(request_id: str) -> bytes:
    """Key for pre-login bootstrap requests (token.get and login.reg)."""
    return hmac.new(request_id.encode(), TUYA_THING_SALT, hashlib.sha256).hexdigest()[:16].encode()


def _get_session_key(request_id: str, ecode: bytes) -> bytes:
    """Key for authenticated session requests (cmd==2 / getEncryptoKey)."""
    msg = TUYA_THING_SALT + b"_" + ecode
    return hmac.new(request_id.encode(), msg, hashlib.sha256).hexdigest()[:16].encode()


def _encrypt_gcm(key: bytes, data: dict[str, Any]) -> str:
    """Encrypt JSON dict with AES-128-GCM into base64(nonce + ct + tag)."""
    pt = json.dumps(data, separators=(",", ":")).encode()
    nonce = os.urandom(12)
    ct_tag = AESGCM(key).encrypt(nonce, pt, None)
    return base64.b64encode(nonce + ct_tag).decode()


def _decrypt_gcm(key: bytes, ct_b64: str) -> dict[str, Any]:
    """Decrypt base64(nonce + ct + tag) with AES-128-GCM into JSON dict."""
    raw = base64.b64decode(ct_b64)
    pt = AESGCM(key).decrypt(raw[:12], raw[12:], None)
    return json.loads(pt.decode())


def _build_canonical(params: dict[str, str]) -> str:
    """Construct the sorted canonical string for HMAC-SHA256 signature."""
    items = []
    for k in sorted(params.keys()):
        if k in _EXCLUDE_FIELDS:
            continue
        v = params[k]
        if k == "postData":
            v = _mobile_hash(v)
        items.append(f"{k}={v}")
    return "||".join(items)


def _calc_sign(canonical: str) -> str:
    """Compute HMAC-SHA256 request signature."""
    return hmac.new(TUYA_THING_SALT, canonical.encode(), hashlib.sha256).hexdigest()


def _encrypt_password_pkcs1(uid: str, pb_key_b64: str) -> str:
    """Encrypt the login.reg password: RSA PKCS#1 v1.5 of uid_password_md5."""
    password_md5 = uid_password_md5(uid)
    der = base64.b64decode(pb_key_b64)
    pub_obj = load_der_public_key(der, backend=default_backend())
    return pub_obj.encrypt(password_md5.encode(), asym_padding.PKCS1v15()).hex()


class TuyaThingClient:
    """Pure Python client for Tuya Thing SDK (et=3) API transport."""

    def __init__(
        self,
        user_id: str,
        country_code: str = "US",
        device_id: str | None = None,
        websession: aiohttp.ClientSession | None = None,
    ) -> None:
        self.user_id = user_id
        self.country_code = country_code
        self.uid = f"eh-{user_id}"
        self.device_id = device_id or "".join(
            random.choices(string.ascii_lowercase + string.digits, k=44)
        )
        self._websession = websession
        self._own_session = False
        self.sid: str | None = None
        self.ecode: bytes = b"z2z6z21241122714"
        self.endpoint: str = TUYA_REGIONS.get(country_code.upper(), TUYA_REGIONS["US"])
        # populated by login(): mobile-MQTT CONNECT inputs (see api/tuya_mqtt.py)
        self.partner_identity: str | None = None
        self.mqtt_url: str | None = None
        # One login shared by all waiters: concurrent callers would each log in and
        # Tuya invalidates the earlier sessions, leaving the losers with a dead sid.
        self._login_lock = asyncio.Lock()
        self._sid_since: float | None = None  # monotonic time of the current sid
        self._session_listeners: list[Callable[[], None]] = []

    def add_session_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call ``listener`` after every login that changed the sid; returns the remover.

        The mobile-MQTT CONNECT username carries the sid, so every subscriber of
        this account must reconnect when any caller logs in again.
        """
        self._session_listeners.append(listener)

        def _remove() -> None:
            if listener in self._session_listeners:
                self._session_listeners.remove(listener)

        return _remove

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._websession is None or self._websession.closed:
            self._websession = aiohttp.ClientSession()
            self._own_session = True
        return self._websession

    async def close(self) -> None:
        if self._own_session and self._websession and not self._websession.closed:
            await self._websession.close()

    async def login(
        self,
        force: bool = False,
        stale_sid: str | None = None,
        min_age: float | None = None,
    ) -> None:
        """Authenticate, coalescing concurrent callers onto a single login.

        ``force`` re-authenticates even when a session exists (periodic refresh).
        ``stale_sid`` is the sid a failed request used: the login is skipped
        when another waiter already replaced it. ``min_age`` (seconds) skips a
        forced login while the session is younger, so one periodic refresh
        serves every caller sharing this client. Session listeners run after a
        login that changed the sid.
        """
        async with self._login_lock:
            if self.sid and not force:
                return  # another waiter already logged in; reuse their sid
            if stale_sid is not None and self.sid and self.sid != stale_sid:
                return
            if (
                min_age is not None
                and self.sid
                and self._sid_since is not None
                and time.monotonic() - self._sid_since < min_age
            ):
                return
            previous = self.sid
            await self._login_impl()
            self._sid_since = time.monotonic()
        if self.sid != previous:
            for listener in list(self._session_listeners):
                try:
                    listener()
                except Exception:  # noqa: BLE001 - one subscriber must not stop the rest
                    _LOGGER.debug("Tuya session listener raised", exc_info=True)

    async def _login_impl(self) -> None:
        """Authenticate with Tuya Thing SDK via the 2-step bootstrap flow."""
        session = await self._get_session()
        bootstrap_endpoint = self.endpoint

        rid1 = str(uuid.uuid4())
        k1 = _get_prelogin_key(rid1)
        pd1 = _encrypt_gcm(k1, {"countryCode": self.country_code, "isUid": True, "username": self.uid})
        params1 = {
            "a": "smartlife.m.user.username.token.get",
            "appVersion": "7.5.0",
            "chKey": TUYA_THING_CHKEY,
            "clientId": TUYA_THING_CLIENT_ID,
            "deviceId": self.device_id,
            "et": "3",
            "lang": "en_US",
            "os": "Android",
            "postData": pd1,
            "requestId": rid1,
            "time": str(int(time.time())),
            "ttid": "android",
            "v": "2.0",
        }
        params1["sign"] = _calc_sign(_build_canonical(params1))

        async with session.post(bootstrap_endpoint, data=params1, timeout=_REQUEST_TIMEOUT) as resp1:
            body1 = await resp1.json(content_type=None)
            if not body1.get("result") or body1.get("success") is False:
                raise TuyaThingError(body1.get("errorCode", "TOKEN_ERR"), body1.get("errorMsg", "token.get failed"))
            res1 = _decrypt_gcm(k1, body1["result"]).get("result", {})
            token = res1.get("token")
            pb_key = res1.get("pbKey")
            if not token or not pb_key:
                raise TuyaThingError("MALFORMED_TOKEN", "Missing token or pbKey in token.get response")

        enc_pass = _encrypt_password_pkcs1(self.uid, pb_key)
        rid2 = str(uuid.uuid4())
        k2 = _get_prelogin_key(rid2)
        pd2 = _encrypt_gcm(k2, {
            "uid": self.uid,
            "createGroup": True,
            "ifencrypt": 1,
            "passwd": enc_pass,
            "countryCode": self.country_code,
            "options": "{\"group\": 1}",
            "token": token,
        })
        params2 = {
            "a": "smartlife.m.user.uid.password.login.reg",
            "appVersion": "7.5.0",
            "chKey": TUYA_THING_CHKEY,
            "clientId": TUYA_THING_CLIENT_ID,
            "deviceId": self.device_id,
            "et": "3",
            "lang": "en_US",
            "os": "Android",
            "postData": pd2,
            "requestId": rid2,
            "time": str(int(time.time())),
            "ttid": "android",
            "v": "1.0",
        }
        params2["sign"] = _calc_sign(_build_canonical(params2))

        async with session.post(bootstrap_endpoint, data=params2, timeout=_REQUEST_TIMEOUT) as resp2:
            body2 = await resp2.json(content_type=None)
            if not body2.get("result") or body2.get("success") is False:
                raise TuyaThingError(body2.get("errorCode", "LOGIN_ERR"), body2.get("errorMsg", "login.reg failed"))
            res2 = _decrypt_gcm(k2, body2["result"])
            if not res2.get("success", True) and "errorCode" in res2:
                raise TuyaThingError(res2["errorCode"], res2.get("errorMsg", "login.reg rejected"))
            data2 = res2.get("result", {})
            self.sid = data2.get("sid")
            if not self.sid:
                raise TuyaThingError("MISSING_SID", "No sid returned from login.reg")
            ecode_val = data2.get("ecode")
            if ecode_val:
                self.ecode = ecode_val.encode() if isinstance(ecode_val, str) else bytes(ecode_val)
            domain = data2.get("domain", {})
            mobile_api_url = domain.get("mobileApiUrl")
            if mobile_api_url:
                self.endpoint = mobile_api_url.rstrip("/") + "/api.json"
            # mobile-MQTT CONNECT inputs; the username carries partnerIdentity + sid
            self.partner_identity = data2.get("partnerIdentity")
            self.mqtt_url = domain.get("mobileMqttsUrl") or domain.get("mobileMqttUrl")

            _LOGGER.debug(
                "Tuya Thing SDK login succeeded: endpoint=%s, client=%x",
                self.endpoint,
                id(self),
            )

    async def request(
        self,
        action: str,
        data: dict[str, Any] | None = None,
        version: str = "1.0",
    ) -> Any:
        """Execute an authenticated Thing SDK action, re-logging in once on a session error.

        Callers swallow TuyaThingError, so without the retry an expired sid turns
        map/room/schedule refresh into a permanent silent no-op.
        """
        if not self.sid:
            await self.login()
        sid = self.sid
        try:
            return await self._request_once(action, data, version)
        except TuyaThingError as err:
            if not is_session_error(err):
                raise
            _LOGGER.debug(
                "Tuya Thing session rejected for %s (%s); re-logging in and retrying",
                action, err,
            )
            await self.login(force=True, stale_sid=sid)
            return await self._request_once(action, data, version)

    async def _request_once(
        self,
        action: str,
        data: dict[str, Any] | None = None,
        version: str = "1.0",
    ) -> Any:
        """One signed Thing SDK round trip. No re-login, no retry."""
        session = await self._get_session()
        rid = str(uuid.uuid4())
        key = _get_session_key(rid, self.ecode)

        params: dict[str, str] = {
            "a": action,
            "appVersion": "7.5.0",
            "chKey": TUYA_THING_CHKEY,
            "clientId": TUYA_THING_CLIENT_ID,
            "deviceId": self.device_id,
            "et": "3",
            "lang": "en_US",
            "os": "Android",
            "requestId": rid,
            "sid": self.sid,  # type: ignore[dict-item]
            "time": str(int(time.time())),
            "ttid": "android",
            "v": version,
        }
        if data is not None:
            params["postData"] = _encrypt_gcm(key, data)

        params["sign"] = _calc_sign(_build_canonical(params))

        # unsigned metadata the gateway expects; added after `sign` on purpose
        params["channel"] = "sdk"
        params["deviceCoreVersion"] = "7.5.0"
        params["sdkVersion"] = "7.5.0"
        params["platform"] = "SM-G960F"
        params["osSystem"] = "10"

        async with session.post(self.endpoint, data=params, timeout=_REQUEST_TIMEOUT) as resp:
            body = await resp.json(content_type=None)
            if body.get("success") is False:
                raise TuyaThingError(body.get("errorCode", resp.status), body.get("errorMsg", "Request failed"))
            res_enc = body.get("result")
            if not res_enc or not isinstance(res_enc, str):
                return body
            decrypted = _decrypt_gcm(key, res_enc)
            if not decrypted.get("success", True) and "errorCode" in decrypted:
                raise TuyaThingError(decrypted["errorCode"], decrypted.get("errorMsg", "Operation failed"))
            return decrypted.get("result", decrypted)
