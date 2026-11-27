"""Eufy Mega (v6 unified app) HTTP client — Python port of eufy-sdk MegaHttpClient."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import time
from collections.abc import Callable
from typing import Any

import aiohttp

from .mega_crypto import (
    SessionEntry,
    decrypt_body,
    encrypt_body,
    finish_key_exchange,
    gtoken,
    login_credentials,
    prepare_key_exchange,
    read_login_reply,
    signed_headers,
)

_LOGGER = logging.getLogger(__name__)
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)

CONF_COUNTRY_CODE = "country_code"
CONF_MEGA_SESSION = "mega_session"
CONF_OPENUDID = "openudid"
DEFAULT_COUNTRY_CODE = "GB"

# Gateway error codes observed in eufy-sdk
CODE_SESSION_KICKED = 26084
CODE_IDENTITY_KEY_STALE = 4404
CODE_SIGNATURE_INVALID = 4416
CODE_PROBE_RETRY = 10000
CODE_CAPTCHA_REQUIRED = 100032
CODE_CAPTCHA_WRONG = 100033

_TOKEN_REJECTED_RE = re.compile(
    r"user_id is empty|invalid[^,]*\btoken\b|\btoken\b[^,]*(expired|error|not exist)"
    r"|kicked|(?:\btoken\b|\bsession\b)[^,]*does not exist|unauthor",
    re.IGNORECASE,
)

# Realistic Android device models, chosen deterministically from openudid.
_PHONE_MODELS = (
    "Pixel 8 Pro",
    "Pixel 9",
    "SM-S918B",
    "SM-S928B",
    "SM-S911B",
    "OnePlus 12",
)

# Model prefixes for Eufy robot vacuums (excludes T28xx mowers, T8xxx/T7xxx/T9xxx security/lights).
_VACUUM_MODEL_PREFIXES = ("T1250", "T20", "T21", "T22", "T23")

# EU/UK country codes default to eu-pr before estimate_domain runs.
_EU_COUNTRIES = frozenset(
    {
        "AT", "BE", "BG", "CH", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR",
        "GB", "GR", "HR", "HU", "IE", "IS", "IT", "LT", "LU", "LV", "MT", "NL",
        "NO", "PL", "PT", "RO", "SE", "SI", "SK", "UK",
    }
)


class MegaApiError(Exception):
    """Non-zero envelope code from the Mega gateway."""

    def __init__(
        self,
        message: str,
        code: int | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class MegaSessionExpiredError(MegaApiError):
    """Persisted or active Mega token was rejected and could not be silently renewed."""


class MegaCaptchaRequiredError(Exception):
    """Login requires solving a captcha challenge."""

    def __init__(self, captcha_id: str, image: str, retry: bool = False) -> None:
        super().__init__("Captcha verification required")
        self.captcha_id = captcha_id
        self.image = image
        self.retry = retry


class MegaTwoFactorRequiredError(Exception):
    """Login requires submitting a 2FA verification code."""

    def __init__(self, method: str = "email") -> None:
        super().__init__("Two-factor verification code required")
        self.method = method


def _default_region_for_country(country_code: str) -> str:
    return "eu-pr" if country_code.upper() in _EU_COUNTRIES else "us-pr"


def _pick_phone_model(openudid: str) -> str:
    digest = hashlib.sha256(openudid.encode("utf-8")).digest()
    return _PHONE_MODELS[digest[0] % len(_PHONE_MODELS)]


def _parse_maybe_json(text: str) -> Any:
    if not text:
        return ""
    try:
        return json.loads(text)
    except ValueError:
        return text


def _token_rejected(code: int | None, msg: str | None) -> bool:
    return code == CODE_SESSION_KICKED or bool(_TOKEN_REJECTED_RE.search(msg or ""))


def _is_vacuum_model(model: str) -> bool:
    code = model.strip().upper()
    return any(code.startswith(prefix) for prefix in _VACUUM_MODEL_PREFIXES)


def _normalize_dps(raw_dps: Any) -> dict[str, Any]:
    if isinstance(raw_dps, dict):
        return raw_dps
    if isinstance(raw_dps, str) and raw_dps.strip():
        try:
            parsed = json.loads(raw_dps)
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            pass
    return {}


class MegaHTTPClient:
    """Signed + encrypted HTTP client for the Eufy v6 (Mega) cloud."""

    def __init__(
        self,
        email: str,
        password: str,
        websession: aiohttp.ClientSession,
        country_code: str = DEFAULT_COUNTRY_CODE,
        openudid: str | None = None,
        session_data: dict[str, Any] | None = None,
        on_session_updated: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.email = email
        self.password = password
        self._websession = websession
        self.country_code = (country_code or DEFAULT_COUNTRY_CODE).strip().upper()
        self.app_name = "eufy_mega"
        self.app_version = "6.0.41_26142"
        self.os_version = "36"
        self._on_session_updated = on_session_updated

        saved = session_data if isinstance(session_data, dict) else {}
        self.openudid: str = openudid or saved.get("openudid") or secrets.token_hex(8)
        self.phone_model: str = saved.get("phone_model") or _pick_phone_model(self.openudid)
        self.region: str = saved.get("region") or _default_region_for_country(self.country_code)
        self.estimated_domain: str = saved.get("estimated_domain") or ""
        self.bootstrap_domain: str | None = saved.get("bootstrap_domain") or None

        self.user_id: str | None = None
        self.account_user_id: str | None = None
        self.auth_token: str | None = None
        self.geo_key: str | None = None
        self.token_expires_at: float = 0.0
        self.session_key: SessionEntry | None = None

        self._pending_captcha_id: str | None = None
        self._pending_2fa: bool = False
        self._logging_in: bool = False
        self._content_type_by_host: dict[str, str] = {}
        self._domain_estimated: bool = bool(self.estimated_domain)

        self._restore_session(saved)

    def _restore_session(self, saved: dict[str, Any]) -> None:
        """Hydrate persisted token and ECDH session key if still valid."""
        if not saved:
            return
        saved_country = saved.get("country_code")
        if saved_country and saved_country.upper() != self.country_code:
            _LOGGER.debug(
                "Saved Mega session country %s != configured %s; ignoring saved token",
                saved_country,
                self.country_code,
            )
            return
        auth_token = saved.get("auth_token")
        user_id = saved.get("user_id")
        share_key = saved.get("share_key")
        key_ident = saved.get("key_ident")
        expires_at = float(saved.get("token_expires_at") or 0)
        if not (auth_token and user_id and share_key and key_ident):
            return
        if expires_at > 0 and time.time() >= expires_at - 300:
            _LOGGER.debug("Saved Mega session token has expired")
            return

        self.user_id = str(user_id)
        self.account_user_id = str(saved.get("account_user_id") or user_id)
        self.auth_token = str(auth_token)
        self.geo_key = saved.get("geo_key")
        self.token_expires_at = expires_at
        self.session_key = SessionEntry(
            key_ident=str(key_ident),
            share_key=str(share_key),
            created_at=float(saved.get("saved_at") or time.time()),
        )
        _LOGGER.debug("Restored persisted Mega session for user %s", self.user_id)

    @property
    def has_valid_session(self) -> bool:
        """Return True when a usable auth token and ECDH key are loaded."""
        return bool(self.auth_token and self.session_key and not self._pending_2fa)

    def export_session(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of the current session."""
        if not (self.auth_token and self.user_id and self.session_key):
            return {}
        return {
            "user_id": self.user_id,
            "account_user_id": self.account_user_id or self.user_id,
            "auth_token": self.auth_token,
            "geo_key": self.geo_key,
            "region": self.region,
            "country_code": self.country_code,
            "estimated_domain": self.estimated_domain,
            "bootstrap_domain": self.bootstrap_domain or "",
            "openudid": self.openudid,
            "phone_model": self.phone_model,
            "share_key": self.session_key.share_key,
            "key_ident": self.session_key.key_ident,
            "token_expires_at": self.token_expires_at,
            "saved_at": time.time(),
        }

    def _persist(self) -> None:
        if self._on_session_updated:
            snapshot = self.export_session()
            if snapshot:
                self._on_session_updated(snapshot)

    def clear_session(self) -> None:
        """Clear auth tokens and ECDH key (keeps stable openudid + phone_model)."""
        self.user_id = None
        self.account_user_id = None
        self.auth_token = None
        self.geo_key = None
        self.token_expires_at = 0.0
        self.session_key = None
        self._pending_captcha_id = None
        self._pending_2fa = False

    def _base_headers(self) -> dict[str, str]:
        return {
            "app-name": self.app_name,
            "app-version": self.app_version,
            "app_version": self.app_version,
            "os-type": "android",
            "os_type": "android",
            "os-version": self.os_version,
            "os_version": self.os_version,
            "phone-model": self.phone_model,
            "phone_model": self.phone_model,
            "model-type": "PHONE",
            "country": self.country_code,
            "ab_code": self.country_code,
            "openudid": self.openudid,
            "language": "en",
            "test-flag": "false",
            "user-agent": "ktor-client",
            "accept": "application/json",
            "accept-charset": "UTF-8",
        }

    def _auth_token_headers(self) -> dict[str, str]:
        if not self.auth_token:
            return {}
        gtoken_uid = self.account_user_id or self.user_id or ""
        return {
            "x-auth-token": self.auth_token,
            "authorization": self.auth_token,
            "gtoken": gtoken(gtoken_uid),
        }

    async def _http_post(
        self,
        url: str,
        body: str | dict[str, Any],
        headers: dict[str, str],
    ) -> tuple[int, Any]:
        payload = (
            body.encode("utf-8")
            if isinstance(body, str)
            else json.dumps(body, separators=(",", ":")).encode("utf-8")
        )
        async with self._websession.post(
            url,
            data=payload,
            headers=headers,
            timeout=_REQUEST_TIMEOUT,
        ) as response:
            text = await response.text()
            return response.status, _parse_maybe_json(text)

    async def estimate_domain(self) -> None:
        """Discover the account's Mega region shard and bootstrap host."""
        url = f"https://mega-{self.region}.eufy.com/passport/estimate_domain"
        headers = {**self._base_headers(), "content-type": "application/json"}
        status, data = await self._http_post(
            url,
            {"ab": self.country_code.lower(), "mode": 1},
            headers,
        )
        _LOGGER.debug("Mega estimate_domain (%s): %s", status, str(data)[:300])
        env = data if isinstance(data, dict) else {}
        raw_payload = env.get("data")
        payload: dict[str, Any] = (
            raw_payload if isinstance(raw_payload, dict) else {}
        )
        domain = str(
            payload.get("domain")
            or payload.get("host")
            or payload.get("server_secret_info")
            or ""
        )
        self.estimated_domain = domain
        blob = json.dumps(payload)
        if "-eu-" in blob or "-eu-" in domain:
            self.region = "eu-pr"
        elif "-us-" in blob or "-us-" in domain:
            self.region = "us-pr"
        if domain and not domain.startswith("mega-"):
            self.bootstrap_domain = domain
        self._domain_estimated = True
        _LOGGER.debug("Mega region resolved to %s (bootstrap=%s)", self.region, self.bootstrap_domain)

    async def ensure_session_key(self) -> SessionEntry:
        """Ensure an active ECDH session key for the current region."""
        if self.session_key and (time.time() - self.session_key.created_at) < 12 * 3600:
            return self.session_key

        host = self.bootstrap_domain or f"app-openapi-{self.region}.eufy.com"
        prep = prepare_key_exchange()
        headers = {
            **self._base_headers(),
            **prep.headers,
            **self._auth_token_headers(),
            "content-type": "application/json",
        }
        status, data = await self._http_post(
            f"https://{host}/openapi/oauth/key/exchange",
            {"client_public_key": prep.encrypted_client_public_key},
            headers,
        )
        env = data if isinstance(data, dict) else {}
        raw_inner = env.get("data")
        inner: dict[str, Any] = raw_inner if isinstance(raw_inner, dict) else {}
        server_pub = inner.get("server_public_key")
        if status != 200 or env.get("code") != 0 or not server_pub:
            raise MegaApiError(
                f"key/exchange failed ({status}/{env.get('code')}): {env.get('msg') or str(data)[:160]}",
                code=env.get("code"),
                status=status,
            )
        self.session_key = finish_key_exchange(prep, str(server_pub))
        _LOGGER.debug("Mega ECDH key exchange complete (authed=%s)", bool(self.auth_token))
        return self.session_key

    async def post_signed(
        self,
        host: str,
        path: str,
        body: Any = None,
        authed: bool = True,
        header_overrides: dict[str, str] | None = None,
        _retried_identity: bool = False,
        _retried_reauth: bool = False,
    ) -> Any:
        """Send an algo_ecdh signed and encrypted POST request."""
        entry = await self.ensure_session_key()
        body_json = json.dumps(body if body is not None else {}, separators=(",", ":"))
        enc_body = encrypt_body(body_json, entry.share_key)

        cached_ct = self._content_type_by_host.get(host)
        preferred = cached_ct or ("text/plain" if "/passport/" in path else "application/json")
        order = (
            ("text/plain", "application/json")
            if preferred == "text/plain"
            else ("application/json", "text/plain")
        )

        last_code: int | None = None
        last_status: int | None = None
        last_msg: str = ""

        for content_type in order:
            headers = {
                **self._base_headers(),
                "content-type": content_type,
                **signed_headers(entry, enc_body),
                "x-replay-info": "replay",
                **(header_overrides or {}),
            }
            if authed:
                headers.update(self._auth_token_headers())

            status, data = await self._http_post(f"https://{host}{path}", enc_body, headers)
            env = data if isinstance(data, dict) else {}
            code = env.get("code")

            if status == 200 and code == 0:
                self._content_type_by_host[host] = content_type
                resp_data = env.get("data")
                if isinstance(resp_data, str) and resp_data:
                    pt = decrypt_body(resp_data, entry.share_key).decode("utf-8")
                    return _parse_maybe_json(pt)
                return resp_data

            detail = str(env.get("msg") or str(data)[:200])
            resp_data = env.get("data")
            if isinstance(resp_data, str) and resp_data:
                try:
                    dec_err = decrypt_body(resp_data, entry.share_key).decode("utf-8")
                    detail = f"{detail} | data={dec_err[:300]}"
                except Exception:  # noqa: BLE001
                    pass

            last_code = code if isinstance(code, int) else None
            last_status = status
            last_msg = detail

            retryable = (
                (status == 403 and last_code == CODE_SIGNATURE_INVALID)
                or last_code == CODE_PROBE_RETRY
                or status == 400
            )
            if not retryable:
                break

        # Server rotated our ECDH key_ident (code 4404): re-exchange once and retry.
        identity_error = authed and (
            last_code == CODE_IDENTITY_KEY_STALE
            or "identity error" in last_msg.lower()
        )
        if identity_error and not _retried_identity and self.auth_token:
            _LOGGER.debug("Mega identity error (4404); re-exchanging session key")
            self.session_key = None
            try:
                await self.ensure_session_key()
            except Exception as err:
                self.clear_session()
                raise MegaSessionExpiredError(
                    f"{path} failed (key re-exchange rejected): {last_msg}",
                    code=last_code,
                    status=last_status,
                ) from err
            self._persist()
            return await self.post_signed(
                host,
                path,
                body=body,
                authed=authed,
                header_overrides=header_overrides,
                _retried_identity=True,
                _retried_reauth=_retried_reauth,
            )

        token_finished = (identity_error and _retried_identity) or (
            authed and last_status == 401 and _token_rejected(last_code, last_msg)
        )
        if token_finished:
            # Attempt a single silent re-login if not already logging in or mid-2FA.
            if (
                not _retried_reauth
                and not self._logging_in
                and not self._pending_2fa
                and self.email
                and self.password
            ):
                _LOGGER.info("Mega token rejected; attempting silent re-login")
                self.clear_session()
                try:
                    await self.login()
                except (MegaCaptchaRequiredError, MegaTwoFactorRequiredError) as challenge:
                    raise MegaSessionExpiredError(
                        f"Session expired and re-login requires verification: {challenge}",
                        code=last_code,
                        status=last_status,
                    ) from challenge
                except Exception as err:
                    raise MegaSessionExpiredError(
                        f"Session expired and re-login failed: {err}",
                        code=last_code,
                        status=last_status,
                    ) from err
                return await self.post_signed(
                    host,
                    path,
                    body=body,
                    authed=authed,
                    header_overrides=header_overrides,
                    _retried_identity=False,
                    _retried_reauth=True,
                )
            self.clear_session()
            raise MegaSessionExpiredError(
                f"{path} failed ({last_status}/{last_code}): {last_msg}",
                code=last_code,
                status=last_status,
            )

        raise MegaApiError(
            f"{path} failed ({last_status}/{last_code}): {last_msg}",
            code=last_code,
            status=last_status,
        )

    async def post(
        self,
        service: str,
        path: str,
        body: Any = None,
        header_overrides: dict[str, str] | None = None,
    ) -> Any:
        """Send an authenticated signed POST to app-{service}-{region}.eufy.com."""
        return await self.post_signed(
            f"app-{service}-{self.region}.eufy.com",
            path,
            body=body,
            authed=True,
            header_overrides=header_overrides,
        )

    def _login_body(
        self,
        *,
        verify_code: str | None = None,
        captcha_id: str | None = None,
        answer: str | None = None,
    ) -> dict[str, Any]:
        base = login_credentials(self.email, self.password, self.country_code)
        if verify_code:
            return {**base, "verify_code": verify_code, "login_id": ""}
        if captcha_id:
            return {
                **base,
                "answer": answer or "",
                "captcha_id": captcha_id,
                "verify_code": "",
                "login_id": "",
            }
        return {**base, "answer": "", "captcha_id": "", "verify_code": "", "login_id": ""}

    async def generate_captcha(self) -> tuple[str, str]:
        """Fetch a fresh captcha challenge (captcha_id, data_uri_image)."""
        res = await self.post_signed(
            f"app-passport-{self.region}.eufy.com",
            "/passport/generate/captcha",
            body={},
            authed=False,
        )
        captcha_id = str(res.get("captcha_id") or "")
        image = str(res.get("item") or "")
        if image and not image.startswith("data:"):
            image = f"data:image/png;base64,{image}"
        return captcha_id, image

    async def send_verify_code(self, message_type: int = 2) -> None:
        """Trigger 2FA verify code delivery (2 = email, 1 = SMS)."""
        await self.post_signed(
            f"app-push-{self.region}.eufy.com",
            "/app/sendmsg/verify_code",
            body={
                "biz_type": 1004,
                "message_type": message_type,
                "transaction": str(int(time.time() * 1000)),
            },
            authed=True,
        )

    async def login(self, message_type: int = 2) -> dict[str, Any]:
        """Log in or reuse a restored session."""
        if self.has_valid_session:
            return {
                "user_id": self.account_user_id or self.user_id,
                "ap_cloud_user_id": self.user_id,
                "access_token": self.auth_token,
                "restored": True,
            }
        return await self._attempt_login(self._login_body(), message_type)

    async def solve_captcha(self, answer: str, message_type: int = 2) -> dict[str, Any]:
        """Continue login with a user-solved captcha answer."""
        if not self._pending_captcha_id:
            raise MegaApiError("No pending captcha challenge")
        return await self._attempt_login(
            self._login_body(captcha_id=self._pending_captcha_id, answer=answer.strip()),
            message_type,
        )

    async def submit_verify_code(self, code: str) -> dict[str, Any]:
        """Continue login with a 2FA verification code."""
        return await self._attempt_login(
            self._login_body(verify_code=code.strip()),
            message_type=2,
        )

    async def _attempt_login(
        self, body: dict[str, Any], message_type: int
    ) -> dict[str, Any]:
        self._logging_in = True
        try:
            if not self._domain_estimated:
                await self.estimate_domain()
            await self.ensure_session_key()

            passport_host = f"app-passport-{self.region}.eufy.com"
            is_verify = bool(body.get("verify_code"))

            try:
                res = await self.post_signed(
                    passport_host,
                    "/passport/login",
                    body=body,
                    authed=bool(self.auth_token),
                )
            except MegaApiError as err:
                if err.code in (CODE_CAPTCHA_REQUIRED, CODE_CAPTCHA_WRONG):
                    captcha_id, image = await self.generate_captcha()
                    self._pending_captcha_id = captcha_id
                    raise MegaCaptchaRequiredError(
                        captcha_id=captcha_id,
                        image=image,
                        retry=(err.code == CODE_CAPTCHA_WRONG),
                    ) from err
                raise

            if not isinstance(res, dict):
                raise MegaApiError(f"Unexpected login response: {str(res)[:200]}")

            reply = read_login_reply(res)
            if not reply:
                raise MegaApiError(f"Login returned no session: {str(res)[:200]}")

            self.user_id = reply["user_id"]
            self.account_user_id = reply["account_user_id"]
            self.auth_token = reply["auth_token"]
            self.geo_key = reply["geo_key"]

            if not is_verify and reply["two_factor_pending"]:
                self._pending_captcha_id = None
                self._pending_2fa = True
                await self.send_verify_code(message_type)
                method = "email" if message_type == 2 else "SMS"
                raise MegaTwoFactorRequiredError(method=method)

            self._pending_captcha_id = None
            self._pending_2fa = False
            self.token_expires_at = reply["token_expires_at"]

            # Re-exchange ECDH key WITH auth token so the gateway binds key_ident to user.
            self.session_key = None
            await self.ensure_session_key()
            self._persist()

            return {
                "user_id": self.account_user_id or self.user_id,
                "ap_cloud_user_id": self.user_id,
                "access_token": self.auth_token,
                "raw": res,
            }
        finally:
            self._logging_in = False

    async def get_user_mqtt_info(self, app_name: str | None = None) -> dict[str, Any]:
        """Fetch per-user mTLS MQTT credentials."""
        overrides = {"app-name": app_name} if app_name else None
        creds = await self.post(
            "devicemanage",
            "/app/devicemanage/get_user_mqtt_info",
            body={},
            header_overrides=overrides,
        )
        if not isinstance(creds, dict):
            return {}
        # Ensure keys expected by EufyCleanCoordinator are always populated.
        uid = creds.get("user_id") or self.user_id or self.account_user_id or ""
        effective_app = creds.get("app_name") or app_name or self.app_name
        creds.setdefault("user_id", uid)
        creds.setdefault("app_name", effective_app)
        creds.setdefault("thing_name", f"{uid}-{effective_app}")
        return creds

    async def get_device_relation_list(self) -> list[dict[str, Any]]:
        """Fetch clean-line devices with last-known DPS snapshots."""
        res = await self.post(
            "devicerelation",
            "/app/devicerelation/get_device_list",
            body={"attribute": 7, "house_id": ""},
            header_overrides={"category": "eufy_home"},
        )
        if not isinstance(res, dict):
            return []
        raw_devices = res.get("devices") or []
        if isinstance(raw_devices, dict):
            raw_devices = raw_devices.get("devices") or []
        if not isinstance(raw_devices, list):
            return []

        results: list[dict[str, Any]] = []
        for item in raw_devices:
            if not isinstance(item, dict):
                continue
            nested = item.get("device")
            dev: dict[str, Any] = nested if isinstance(nested, dict) else item
            if dev.get("device_sn"):
                results.append(dev)
        return results

    async def get_house_devices(self) -> list[dict[str, Any]]:
        """Fetch devices across default and per-house Mega endpoints."""
        bodies: list[dict[str, Any]] = [{}]
        try:
            houses = await self.post("house", "/app/house/get_house_list", body={})
            if isinstance(houses, dict):
                for h in houses.get("house_infos") or []:
                    if isinstance(h, dict) and h.get("house_id"):
                        bodies.append({"house_id": h["house_id"]})
        except MegaSessionExpiredError:
            raise
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Mega get_house_list failed: %s", err)

        by_sn: dict[str, dict[str, Any]] = {}
        for body in bodies:
            try:
                res = await self.post("house", "/app/house/get_devs_list", body=body)
            except MegaSessionExpiredError:
                raise
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Mega get_devs_list(%s) failed: %s", body, err)
                continue
            if not isinstance(res, dict):
                continue
            for raw in res.get("devices") or []:
                if isinstance(raw, dict) and raw.get("device_sn"):
                    by_sn[raw["device_sn"]] = raw
        return list(by_sn.values())

    async def discover_vacuum_devices(self) -> list[dict[str, Any]]:
        """Discover robot vacuums by merging devicerelation DPS with house metadata."""
        merged: dict[str, dict[str, Any]] = {}

        # 1. House list gives full metadata (alias_name, device_model, category, firmware).
        for raw in await self.get_house_devices():
            sn = raw.get("device_sn")
            model = str(raw.get("device_model") or "")
            category = str(raw.get("category") or "")
            if not sn:
                continue
            if category in ("eufy_security", "eufy_life"):
                continue
            if not (_is_vacuum_model(model) or category in ("eufy_home", "eufy_home_tuya", "robovac")):
                continue
            merged[sn] = {
                "device_sn": sn,
                "device_model": model,
                "alias_name": raw.get("alias_name") or raw.get("device_alias_name") or "",
                "device_name": raw.get("device_name") or "",
                "main_sw_version": raw.get("main_sw_version") or raw.get("soft_version") or "",
                "category": category,
                "dps": _normalize_dps(raw.get("dps")),
                "_reconstructed": category == "eufy_home_tuya",
            }

        # 2. devicerelation/get_device_list enriches devices with last-known DPS snapshots.
        try:
            rel_devices = await self.get_device_relation_list()
        except MegaSessionExpiredError:
            raise
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Mega get_device_relation_list failed: %s", err)
            rel_devices = []

        for dev in rel_devices:
            sn = dev.get("device_sn")
            if not sn:
                continue
            model = str(dev.get("device_model") or "")
            if model and not _is_vacuum_model(model) and sn not in merged:
                continue
            dps = _normalize_dps(dev.get("dps"))
            if sn in merged:
                if dps:
                    merged[sn]["dps"] = {**merged[sn]["dps"], **dps}
                if not merged[sn].get("device_model") and model:
                    merged[sn]["device_model"] = model
                if not merged[sn].get("alias_name") and dev.get("alias_name"):
                    merged[sn]["alias_name"] = dev["alias_name"]
                if not merged[sn].get("device_name") and dev.get("device_name"):
                    merged[sn]["device_name"] = dev["device_name"]
                if not merged[sn].get("main_sw_version"):
                    merged[sn]["main_sw_version"] = (
                        dev.get("main_sw_version") or dev.get("soft_version") or ""
                    )
            else:
                merged[sn] = {
                    "device_sn": sn,
                    "device_model": model,
                    "alias_name": dev.get("alias_name") or "",
                    "device_name": dev.get("device_name") or "",
                    "main_sw_version": dev.get("main_sw_version") or dev.get("soft_version") or "",
                    "category": str(dev.get("category") or "eufy_home"),
                    "dps": dps,
                    "_reconstructed": False,
                }

        devices = list(merged.values())
        _LOGGER.info("Mega discovery found %d vacuum device(s)", len(devices))
        return devices
