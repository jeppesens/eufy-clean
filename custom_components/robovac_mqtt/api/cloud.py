from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from ..auth_store import session_expiry, trim_session, trim_user_info
from ..const import DPS_MAP, EUFY_CLEAN_DEVICES, SCALAR_DPS, TUYA_PRODUCT_MODELS
from ..utils import is_protobuf_dps_value
from .http import EufyHTTPClient, EufyLoginRateLimitedError, EufyLoginTransientError
from .tuya_cloud import TuyaCloudClient, TuyaCloudError
from .tuya_thing import TuyaThingClient, is_session_error

__all__ = [
    "EufyLogin",
    "EufyLoginError",
    "EufyLoginRateLimitedError",
    "EufyLoginTransientError",
]

_LOGGER = logging.getLogger(__name__)

# Seconds without a replacement MQTT login after one failed (Eufy unreachable).
_MQTT_RELOGIN_RETRY_DELAY = 5 * 60.0
# Seconds between successful replacement MQTT logins: a broker that accepts a
# certificate and rejects it again soon after gets no login per cycle.
_MQTT_RELOGIN_MIN_INTERVAL = 3600.0

# Failures of one region probe that must not stop the next region.
_TUYA_PROBE_ERRORS = (
    TuyaCloudError,
    aiohttp.ClientError,
    TimeoutError,
    KeyError,
    TypeError,
    ValueError,
)


def _is_tuya_session_error(err: TuyaCloudError) -> bool:
    """Is this a rejected or missing Tuya session, the only error a login fixes?"""
    return err.code == "NO_SID" or is_session_error(err)


def _is_scalar_state_value(value: Any) -> bool:
    """Is DPS 15 numeric (scalar) rather than a Tuya word status?"""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return value.strip().lstrip("-").isdigit()
    return False


class EufyLoginError(Exception):
    """The Eufy cloud rejected the credentials.

    Transient failures (429, 5xx, network) raise EufyLoginTransientError, which
    is not a subclass.
    """


class EufyLogin:
    def __init__(
        self,
        username: str,
        password: str,
        openudid: str,
        websession: Any | None = None,
        auth_cache: Any | None = None,
    ):
        self.eufyApi = EufyHTTPClient(username, password, openudid, websession=websession)
        self.username = username
        self.password = password
        self.openudid = openudid
        self._websession = websession
        self.mqtt_credentials: dict[str, Any] | None = None
        self.mqtt_devices: list[dict[str, Any]] = []
        self.cloud_devices: list[dict[str, Any]] = []
        self.eufy_api_devices: list[dict[str, Any]] = []
        self.tuya_client: TuyaCloudClient | None = None
        self.tuya_thing_client: TuyaThingClient | None = None
        # Every devId on the Tuya device list (firmware calls need one).
        self.tuya_device_ids: set[str] = set()
        self._eufy_user_id: str | None = None
        # The probe candidate that answered, not the redirect's regionCode.
        self._tuya_probe_region: str | None = None
        # The last discovery could not reach the Tuya cloud (login or list).
        self._tuya_failed = False
        # Serialises Tuya re-logins: each login invalidates the previous sid.
        self._tuya_login_lock = asyncio.Lock()
        # One MQTT-credential login for all coordinators that find none.
        self._check_login_lock = asyncio.Lock()
        # MQTT credentials whose rejection gets no further login: ones a login
        # produced that the broker has not accepted yet, or ones the account
        # login refused.
        self._mqtt_relogin_spent: dict[str, Any] | None = None
        # time.monotonic() before which no replacement login is sent
        self._mqtt_relogin_not_before: float | None = None
        # Persisted handshake reused across restarts; None disables caching.
        self.auth_cache = auth_cache
        if auth_cache is not None:
            self.eufyApi.restore(
                auth_cache.session, auth_cache.user_info, auth_cache.login_label
            )
            self.mqtt_credentials = auth_cache.mqtt_credentials
            if auth_cache.mqtt_credentials_unaccepted and self.mqtt_credentials:
                self._mqtt_relogin_spent = self.mqtt_credentials
            if auth_cache.session:
                self._eufy_user_id = auth_cache.session.get("user_id")

    async def init(self):
        """Authenticate and discover devices, reusing a cached handshake.

        Validated by RESULT, not a timer: a cached run that finds nothing
        discards the cache and re-logs in. A cached run that failed on the
        server side (Eufy 408/5xx, Tuya unreachable) raises
        EufyLoginTransientError instead and keeps the cache. An HTTP 429
        starts the login hold-off and raises EufyLoginRateLimitedError.
        """
        cached = self.auth_cache is not None and self.auth_cache.can_skip_login
        discover = True
        if cached:
            _LOGGER.debug("EufyLogin.init() starting: reusing cached credentials")
            await self._discover()
            proved = self._eufy_session_proved()
            if proved and not self._mqtt_devices_without_credentials():
                self._capture_auth_cache()
                return
            if proved and self.login_hold_off_left() is not None:
                _LOGGER.debug(
                    "Cached session has no MQTT credentials; no login until the "
                    "login hold-off ends"
                )
                self._capture_auth_cache()
                return
            if (
                not proved
                and not self.eufyApi.auth_error
                and (self.eufyApi.transient_error or self._tuya_failed)
            ):
                raise EufyLoginTransientError(
                    "device discovery failed on the server side; keeping the "
                    "cached session"
                )
            if proved:
                # the session just served discovery; only the login is missing
                _LOGGER.info(
                    "Cached Eufy session has no MQTT credentials for %d MQTT "
                    "device(s); logging in again",
                    len(self.mqtt_devices),
                )
                discover = False
            else:
                _LOGGER.info(
                    "Cached Eufy credentials were rejected or found nothing; "
                    "re-authenticating"
                )
                self._reset_after_stale_cache()

        _LOGGER.debug("EufyLogin.init() starting: HTTP login")
        await self.login({"mqtt": True})
        try:
            if discover:
                await self._discover()
        finally:
            # the login succeeded: keep its tokens even if discovery failed
            self._capture_auth_cache()
        if self._mqtt_devices_without_credentials():
            # e.g. a user-center outage: the next setups reuse this session
            # instead of logging in again until the hold-off ends
            self._hold_off_logins(None)

    def _mqtt_devices_without_credentials(self) -> bool:
        """MQTT robots found, but the session holds no MQTT credentials for them."""
        return bool(self.mqtt_devices) and not self.mqtt_credentials

    def login_hold_off_left(self) -> float | None:
        if self.auth_cache is None:
            return None
        return self.auth_cache.login_hold_off_left()

    def _hold_off_logins(self, seconds: float | None) -> None:
        if self.auth_cache is None:
            return
        self.auth_cache.hold_off_logins(seconds)
        _LOGGER.warning(
            "Eufy logins on hold for %.0f s",
            self.auth_cache.login_hold_off_left() or 0.0,
        )

    def _eufy_session_proved(self) -> bool:
        """Did this run prove the cached EUFY token still works?

        Only ``auth_error`` (401/403) decides: Tuya discovery succeeds on a
        dead eufy session, and an account may legitimately own no AIOT device.
        """
        if self.eufyApi.auth_error:
            return False
        return bool(self.eufy_api_devices or self.mqtt_devices or self.cloud_devices)

    async def _discover(self) -> None:
        """Device discovery: the part that is identical cached or not."""
        try:
            await self.getDevices()
        except EufyLoginRateLimitedError as err:
            self._hold_off_logins(err.retry_after)
            raise

        self._tuya_failed = False
        try:
            await self.tuya_login()
            await self.getCloudDevices()
        except Exception as e:
            self._tuya_failed = True
            _LOGGER.warning(
                "Tuya Cloud login failed; legacy cloud devices will be unavailable: %s", e
            )

    def _reset_after_stale_cache(self) -> None:
        """Drop everything derived from a cache that turned out to be stale."""
        if self.auth_cache is not None:
            self.auth_cache.clear_tokens()
        self.eufyApi.restore(None, None, self.eufyApi.login_label)
        self.mqtt_credentials = None
        self._eufy_user_id = None
        self.mqtt_devices = []
        self.cloud_devices = []
        self.eufy_api_devices = []
        self.tuya_client = None
        self.tuya_thing_client = None
        self._tuya_probe_region = None
        self._tuya_failed = False

    def _capture_auth_cache(self) -> None:
        """Copy the live handshake back into the cache for the next restart."""
        cache = self.auth_cache
        if cache is None:
            return
        # A cached session carries no fresh expires_in; keep the stored expiry.
        raw_session = self.eufyApi.session
        cache.session = trim_session(raw_session)
        expiry = session_expiry(raw_session)
        if expiry is not None:
            cache.session_expires_at = expiry
        cache.user_info = trim_user_info(self.eufyApi.user_info)
        cache.mqtt_credentials = self.mqtt_credentials
        cache.mqtt_credentials_unaccepted = (
            self.mqtt_credentials is not None
            and self.mqtt_credentials is self._mqtt_relogin_spent
        )
        # The fallback-session path never sets a label; writing None would
        # erase a previously good memo.
        if self.eufyApi.login_label:
            cache.login_label = self.eufyApi.login_label
        if self._tuya_probe_region is not None:
            cache.tuya_region = self._tuya_probe_region

    async def login(self, config: dict):
        """Log in to Eufy; refused locally while the login hold-off runs."""
        eufyLogin = None

        if not config["mqtt"]:
            raise EufyLoginError("MQTT login is required")

        if (left := self.login_hold_off_left()) is not None:
            raise EufyLoginRateLimitedError(
                f"Eufy logins on hold for another {left:.0f} s",
                retry_after=left,
            )
        try:
            eufyLogin = await self.eufyApi.login()
        except EufyLoginRateLimitedError as err:
            self._hold_off_logins(err.retry_after)
            raise

        if not eufyLogin:
            raise EufyLoginError("Login failed")

        self.mqtt_credentials = eufyLogin["mqtt"]
        self._mqtt_relogin_spent = self.mqtt_credentials
        _LOGGER.debug("HTTP login successful, MQTT credentials obtained")

        session = eufyLogin.get("session", {})
        self._eufy_user_id = session.get("user_id")
        _LOGGER.debug("Eufy user_id: %s", "present" if self._eufy_user_id else "missing")

    @property
    def has_user_center(self) -> bool:
        """False for a fallback-session account, which never gets MQTT credentials."""
        return not (self.eufyApi.session and self.eufyApi.user_info is None)

    async def checkLogin(self):
        """Log in for MQTT credentials when missing and the account can have them."""
        async with self._check_login_lock:
            if self.mqtt_credentials:
                return
            if not self.has_user_center:
                _LOGGER.debug("Fallback-session account: no MQTT credentials to fetch")
                return
            await self.login({"mqtt": True})
            self._capture_auth_cache()

    async def replace_rejected_mqtt_credentials(
        self,
        rejected: dict[str, Any],
        save: Callable[[], Awaitable[None]],
    ) -> bool:
        """Replace MQTT credentials the broker rejects, with one login for all callers.

        The rejected credentials leave the auth cache, so the next setup logs in
        instead of reusing them. No login runs during the login hold-off, nor
        for credentials a login produced (until the broker accepts them; the
        auth cache keeps that mark across a restart) or refused: their
        rejection starts the hold-off, which outlives a restart. Nor within the
        retry delay of a failed replacement login or the minimum interval after
        a successful one.
        ``save`` persists the cache after a change. Returns True when the caller
        should reconnect with ``mqtt_credentials``. Raises EufyLoginError when
        the account login is refused.
        """
        async with self._check_login_lock:
            current = self.mqtt_credentials
            if current and current is not rejected:
                return True
            changed = False
            cache = self.auth_cache
            if cache is not None and cache.mqtt_credentials is not None:
                cache.mqtt_credentials = None
                changed = True
            try:
                if rejected is self._mqtt_relogin_spent:
                    _LOGGER.debug("MQTT credentials from a login rejected; no login")
                    if self.login_hold_off_left() is None:
                        self._hold_off_logins(None)
                        changed = True
                    return False
                if self.login_hold_off_left() is not None:
                    return False
                not_before = self._mqtt_relogin_not_before
                if not_before is not None and time.monotonic() < not_before:
                    _LOGGER.debug("Replacement MQTT login held back; no login")
                    return False
                changed = True
                try:
                    await self.login({"mqtt": True})
                except EufyLoginError:
                    self._mqtt_relogin_spent = rejected
                    raise
                except (
                    EufyLoginTransientError, aiohttp.ClientError, TimeoutError
                ) as err:
                    _LOGGER.warning("Could not fetch new MQTT credentials: %s", err)
                    self._mqtt_relogin_not_before = (
                        time.monotonic() + _MQTT_RELOGIN_RETRY_DELAY
                    )
                    return False
                self._capture_auth_cache()
                if not self.mqtt_credentials:
                    self._hold_off_logins(None)
                    return False
                self._mqtt_relogin_not_before = (
                    time.monotonic() + _MQTT_RELOGIN_MIN_INTERVAL
                )
                _LOGGER.info("Fetched new MQTT credentials after a broker rejection")
                return True
            finally:
                if changed:
                    await save()

    def mqtt_credentials_accepted(self, credentials: dict[str, Any] | None) -> bool:
        """The broker accepted ``credentials``: a later rejection may log in again.

        Returns True when the auth cache changed and should be saved.
        """
        if credentials is None or credentials is not self._mqtt_relogin_spent:
            return False
        self._mqtt_relogin_spent = None
        cache = self.auth_cache
        if cache is None or not cache.mqtt_credentials_unaccepted:
            return False
        cache.mqtt_credentials_unaccepted = False
        return True

    async def tuya_login(self) -> None:
        """Log in to the Tuya cloud with the Eufy user_id, probing EU then US."""
        if not self._eufy_user_id:
            _LOGGER.debug("No Eufy user_id available; skipping Tuya Cloud login")
            return

        # Reordered (never filtered) so a remembered region that stops working
        # still falls back to the other.
        regions = ["EU", "US"]
        remembered = self.auth_cache.tuya_region if self.auth_cache else None
        if remembered in regions:
            regions.remove(remembered)
            regions.insert(0, remembered)

        last_error: Exception | None = None
        for region in regions:
            try:
                client = TuyaCloudClient(region, websession=self._websession)
                await client.login(self._eufy_user_id)
            except _TUYA_PROBE_ERRORS as err:
                _LOGGER.debug("Tuya Cloud %s login failed: %s", region, err)
                last_error = err
                continue
            self.tuya_client = client
            # The PROBED region, not client.region: a redirect rewrites that
            # to a regionCode ("AZ") that is not a probe candidate.
            self._tuya_probe_region = region
            _LOGGER.debug("Tuya Cloud login successful (%s)", region)
            break
        else:
            if last_error is None:
                last_error = TuyaCloudError("LOGIN_FAILED", "Tuya Cloud login failed")
            raise last_error

        # Also the probed region: a regionCode is not a country code here.
        region = self._tuya_probe_region or "US"
        self.tuya_thing_client = TuyaThingClient(
            user_id=self._eufy_user_id,
            country_code=region,
            websession=self._websession,
        )

    async def _tuya_relogin(self, failed_sid: str | None) -> None:
        """Re-authenticate the existing Tuya client, once for all waiters.

        ``failed_sid`` is the sid the failed request used; a waiter that finds
        a different sid reuses the login another waiter already made.
        """
        async with self._tuya_login_lock:
            client = self.tuya_client
            if client is None or not self._eufy_user_id:
                raise TuyaCloudError("NO_CLIENT", "No Tuya client to re-login")
            if client.sid and client.sid != failed_sid:
                return
            await client.login(self._eufy_user_id)

    async def getDevices(self) -> None:
        self.eufy_api_devices = await self.eufyApi.get_cloud_device_list()
        _LOGGER.debug("Eufy API returned %d devices from cloud list", len(self.eufy_api_devices))
        devices = await self.eufyApi.get_device_list()
        # v2 accounts can return an empty AIOT list while the cloud list has
        # entries; rebuild minimal entries so MQTT setup still works.
        if not devices and self.eufy_api_devices:
            _LOGGER.info(
                "AIOT device list empty — constructing device entries from cloud device list"
            )
            devices = [
                {"device_sn": d["id"], "dps": {}, "_reconstructed": True}
                for d in self.eufy_api_devices
                if d.get("id")
            ]
        devices = [
            {
                **self.findModel(device.get("device_sn", ""), aiot_device=device),
                "apiType": self.checkApiType(device.get("dps", {})),
                "mqtt": True,
                "dps": device.get("dps", {}),
                "softVersion": device.get("main_sw_version")
                or device.get("soft_version")
                or "",
                # Placeholder only; a Tuya device with a localKey supersedes it.
                "reconstructed": device.get("_reconstructed", False),
            }
            for device in devices
            if device.get("device_sn")
        ]
        self.mqtt_devices = [d for d in devices if not d["invalid"]]
        _LOGGER.debug(
            "MQTT devices: %d valid out of %d total (%s)",
            len(self.mqtt_devices),
            len(devices),
            [(d["deviceName"], d["apiType"]) for d in self.mqtt_devices],
        )

    async def getCloudDevices(self) -> None:
        """Fetch devices from Tuya Cloud and add those not already in MQTT list.

        ``localKey`` is the Tuya v3 credential; ``ip`` is the public address,
        rarely a usable LAN target.
        """
        if not self.tuya_client:
            return

        try:
            # Setup-time discovery must not miss a newly added device.
            tuya_devices = await self.tuya_client.get_device_list(force=True)
        except TuyaCloudError as e:
            self._tuya_failed = True
            _LOGGER.warning("Failed to fetch Tuya Cloud device list: %s", e)
            return
        self.tuya_device_ids = {
            d["devId"] for d in tuya_devices if isinstance(d, dict) and d.get("devId")
        }

        # A keyed Tuya device must SUPERSEDE a placeholder, not be dropped as
        # a duplicate, else it is stuck on an MQTT path it cannot answer.
        confirmed_ids = {
            d["deviceId"] for d in self.mqtt_devices if not d.get("reconstructed")
        }
        reconstructed_ids = {
            d["deviceId"] for d in self.mqtt_devices if d.get("reconstructed")
        }
        superseded_ids: set[str] = set()
        seen_cloud_ids: set[str] = set()

        for device in tuya_devices:
            dev_id = device.get("devId")
            if not dev_id:
                _LOGGER.debug(
                    "Cloud device skipping (no devId): keys=%s",
                    sorted(device) if isinstance(device, dict) else type(device).__name__,
                )
                continue
            if dev_id in seen_cloud_ids:
                _LOGGER.debug("Cloud device %s: skipping (duplicate Tuya record)", dev_id)
                continue
            if dev_id in confirmed_ids:
                _LOGGER.debug(
                    "Cloud device %s: skipping (already a confirmed MQTT device)",
                    dev_id,
                )
                continue
            if dev_id in reconstructed_ids:
                superseded_ids.add(dev_id)
                _LOGGER.debug(
                    "Cloud device %s: superseding reconstructed MQTT placeholder "
                    "with the Tuya cloud/local device",
                    dev_id,
                )

            model_info = self.findModel(dev_id, tuya_device=device)
            if model_info["invalid"]:
                _LOGGER.debug(
                    "Cloud device %s: skipping (no model and no localKey)", dev_id
                )
                continue
            if not model_info["deviceModel"]:
                _LOGGER.warning(
                    "Cloud device %s kept with unknown model "
                    "(productId=%s, name=%s); report this so a "
                    "TUYA_PRODUCT_MODELS mapping can be added",
                    dev_id,
                    device.get("productId") or device.get("productKey"),
                    device.get("name"),
                )

            dps = self._coerce_dps(device.get("dps"))
            local_key = device.get("localKey") or ""
            api_type = self.checkApiType(dps)
            # Omitted from the device list and used only by the legacy path.
            tuya_schema = (
                await self.tuya_client.get_device_schema(dev_id)
                if api_type == "legacy"
                else {}
            )
            self.cloud_devices.append(
                {
                    **model_info,
                    "apiType": api_type,
                    "mqtt": False,
                    "dps": dps,
                    "softVersion": "",
                    # Lets the coordinator promote to direct local push.
                    "local_key": local_key,
                    "tuya_public_ip": device.get("ip") or "",
                    # Per-device DPS vocabulary; the legacy path prefers it.
                    "tuya_schema": tuya_schema,
                }
            )
            seen_cloud_ids.add(dev_id)

        if superseded_ids:
            self.mqtt_devices = [
                d for d in self.mqtt_devices if d["deviceId"] not in superseded_ids
            ]

        # One leftover placeholder plus one unmatched keyed Tuya device is the
        # same robot under two ids; drop it, or one vacuum gets 2 coordinators.
        if not superseded_ids:
            leftover = [
                d
                for d in self.mqtt_devices
                if d.get("reconstructed") and d["deviceId"] not in seen_cloud_ids
            ]
            keyed_cloud = [d for d in self.cloud_devices if d.get("local_key")]
            if len(leftover) == 1 and len(keyed_cloud) == 1:
                self.mqtt_devices = [
                    d for d in self.mqtt_devices if d is not leftover[0]
                ]
                _LOGGER.debug(
                    "Dropped lone reconstructed placeholder %s in favour of the "
                    "single Tuya cloud device %s (id mismatch, same robot)",
                    leftover[0]["deviceId"],
                    keyed_cloud[0]["deviceId"],
                )

        if self.cloud_devices:
            _LOGGER.info(
                "Found %d Tuya Cloud device(s): %s",
                len(self.cloud_devices),
                [d["deviceName"] for d in self.cloud_devices],
            )

    @staticmethod
    def _coerce_dps(value: Any) -> dict[str, Any]:
        """Tuya cloud may return dps as a JSON string OR a dict — normalise."""
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:  # noqa: BLE001
                return {}
        if isinstance(value, dict):
            return value
        return {}

    async def getCloudDevice(self, device_id: str) -> dict[str, Any] | None:
        """Poll a cloud device's DPS; on a session error re-login and retry once."""
        client = self.tuya_client
        if not client:
            _LOGGER.warning("Cannot poll cloud device: no Tuya client")
            return None

        sid = client.sid
        try:
            result = await client.get_device(device_id)
            _LOGGER.debug(
                "Cloud device %s poll: %s",
                device_id,
                f"{len(result)} DPS keys" if result else "not found",
            )
            return result
        except TuyaCloudError as e:
            if not _is_tuya_session_error(e):
                _LOGGER.debug("Cloud device %s poll failed: %s", device_id, e)
                return None
            _LOGGER.debug("Cloud device %s poll failed: %s; re-logging in", device_id, e)
            try:
                await self._tuya_relogin(sid)
                return await client.get_device(device_id)
            except Exception as retry_err:
                _LOGGER.warning(
                    "Failed to poll cloud device %s after re-login: %s",
                    device_id,
                    retry_err,
                )
                return None

    async def sendCloudCommand(
        self, device_id: str, dps: dict[str, Any]
    ) -> None:
        """Send a command to a cloud device; on a session error re-login and retry once."""
        client = self.tuya_client
        if not client:
            raise EufyLoginError("Cannot send cloud command: no Tuya client")

        sid = client.sid
        try:
            await client.send_command(device_id, dps)
            _LOGGER.debug("Cloud command to %s succeeded: DPS %s", device_id, sorted(dps))
        except TuyaCloudError as e:
            if not _is_tuya_session_error(e):
                raise EufyLoginError(
                    f"Failed to send cloud command to {device_id}: {e}"
                ) from e
            _LOGGER.debug("Cloud command to %s failed: %s; re-logging in", device_id, e)
            try:
                await self._tuya_relogin(sid)
                await client.send_command(device_id, dps)
            except Exception as retry_err:
                raise EufyLoginError(
                    f"Failed to send cloud command to {device_id}: {retry_err}"
                ) from retry_err

    @staticmethod
    def checkApiType(dps: dict):
        """Classify a device's DPS protocol from its initial state snapshot.

        On value SHAPE, not key presence: scalar reuses the protobuf DPS
        numbers with int values. "legacy" = no protobuf DPS at all.
        """
        for key in (DPS_MAP["WORK_STATUS"], DPS_MAP["CLEANING_PARAMETERS"]):
            val = dps.get(key)
            if val is not None:
                return "novel" if is_protobuf_dps_value(val) else "scalar"
        # DPS 15 is scalar status as an INT; legacy Tuya devices report it as a
        # status string ("Running"), which must use the legacy parser.
        state_val = dps.get(SCALAR_DPS["STATE"])
        if state_val is not None and _is_scalar_state_value(state_val):
            return "scalar"
        if any(k in dps for k in DPS_MAP.values()):
            return "novel"
        return "legacy"

    @staticmethod
    def _resolve_model(code: str) -> str:
        """Return the best device model code, falling back to first 5 chars."""
        if code in EUFY_CLEAN_DEVICES:
            return code
        truncated = code[:5]
        if truncated in EUFY_CLEAN_DEVICES:
            return truncated
        return code

    @staticmethod
    def _resolve_tuya_model(tuya_device: dict[str, Any]) -> str:
        """Best-effort model code for a Tuya device with no Eufy v2 match.

        productId table first, then an exact model code in the name.
        """
        product_id = (
            tuya_device.get("productId")
            or tuya_device.get("productKey")
            or ""
        )
        if product_id in TUYA_PRODUCT_MODELS:
            return TUYA_PRODUCT_MODELS[product_id]
        # EXACT model codes only: _resolve_model()'s 5-char truncation would
        # false-positive ("T22610" -> "T2261") on user-set device names.
        name = tuya_device.get("name") or ""
        for token in name.replace("-", " ").split():
            if token in EUFY_CLEAN_DEVICES:
                return token
        return ""

    def findModel(
        self,
        deviceId: str,
        aiot_device: dict | None = None,
        tuya_device: dict | None = None,
    ):
        device = next((d for d in self.eufy_api_devices if d.get("id") == deviceId), None)

        if device:
            raw_code = (
                device.get("product", {}).get("product_code", "")
                or device.get("device_model", "")
            )
            return {
                "deviceId": deviceId,
                "deviceModel": self._resolve_model(raw_code),
                "deviceName": device.get("alias_name")
                or device.get("device_name")
                or device.get("name"),
                "deviceModelName": device.get("product", {}).get("name"),
                "invalid": False,
            }

        # For devices the V2 endpoint has no metadata for.
        if aiot_device:
            # Shared resolver, not [:5]: T2080A must not become T2080.
            model_code = self._resolve_model(aiot_device.get("device_model") or "")
            return {
                "deviceId": deviceId,
                "deviceModel": model_code,
                "deviceName": aiot_device.get("alias_name")
                or aiot_device.get("device_name")
                or "Eufy Robovac",
                "deviceModelName": None,
                "invalid": not bool(model_code),
            }

        # A localKey means a real, controllable device even with an unknown
        # model, so only "no model and no localKey" is invalid.
        if tuya_device is not None:
            model = self._resolve_tuya_model(tuya_device)
            has_local_key = bool(tuya_device.get("localKey"))
            return {
                "deviceId": deviceId,
                "deviceModel": model,
                "deviceName": tuya_device.get("name") or "Eufy Robovac (cloud)",
                "deviceModelName": None,
                "invalid": not (model or has_local_key),
            }

        return {
            "deviceId": deviceId,
            "deviceModel": "",
            "deviceName": "",
            "deviceModelName": "",
            "invalid": True,
        }
