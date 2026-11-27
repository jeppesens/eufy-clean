from __future__ import annotations

import ipaddress
import logging
import re
import secrets
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from voluptuous import In
from voluptuous import Optional as VOptional
from voluptuous import Required, Schema

from .api.cloud import EufyLogin
from .api.mega_http import (
    CONF_COUNTRY_CODE,
    CONF_MEGA_SESSION,
    CONF_OPENUDID,
    DEFAULT_COUNTRY_CODE,
    MegaApiError,
    MegaCaptchaRequiredError,
    MegaTwoFactorRequiredError,
)
from .const import (
    CONF_LOCAL_DEVICES,
    CONF_LOCAL_HOST,
    CONF_LOCAL_VERSION,
    CONF_MAP_ID,
    CONF_MAP_IDS,
    CONF_MAP_MAX_PX,
    CONF_NOTIFY_DESKTOP,
    CONF_NOTIFY_MOBILE_SERVICE,
    CONF_ROBOT_STYLE,
    CONF_ROOM_NAMES,
    DEFAULT_MAP_MAX_PX,
    DEFAULT_NOTIFY_DESKTOP,
    DEFAULT_NOTIFY_MOBILE_SERVICE,
    DEFAULT_ROBOT_STYLE,
    DOMAIN,
    VACS,
)

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Handle a config flow for Eufy Robovac."""

    VERSION = 1

    def __init__(self) -> None:
        self._eufy_login: EufyLogin | None = None
        self._pending_data: dict[str, Any] = {}
        self._flow_mode: str = "user"
        self._target_entry: config_entries.ConfigEntry | None = None
        self._captcha_image: str = ""
        self._two_factor_method: str = "email"

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        return OptionsFlowHandler(config_entry)

    def _default_country(self, entry: config_entries.ConfigEntry | None = None) -> str:
        if entry and entry.data.get(CONF_COUNTRY_CODE):
            return str(entry.data[CONF_COUNTRY_CODE])
        return (self.hass.config.country or DEFAULT_COUNTRY_CODE).upper()

    def _user_schema(
        self,
        *,
        default_username: str | None = None,
        default_country: str | None = None,
    ) -> Schema:
        country = default_country or self._default_country()
        if default_username is not None:
            return Schema(
                {
                    Required(CONF_USERNAME, default=default_username): cv.string,
                    Required(CONF_PASSWORD): cv.string,
                    Required(CONF_COUNTRY_CODE, default=country): cv.string,
                }
            )
        return Schema(
            {
                Required(CONF_USERNAME): cv.string,
                Required(CONF_PASSWORD): cv.string,
                Required(CONF_COUNTRY_CODE, default=country): cv.string,
            }
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=self._user_schema())

        username = user_input[CONF_USERNAME].strip()
        password = user_input[CONF_PASSWORD]
        country = user_input[CONF_COUNTRY_CODE].strip().upper() or DEFAULT_COUNTRY_CODE

        await self.async_set_unique_id(username)
        self._abort_if_unique_id_configured()

        self._flow_mode = "user"
        self._target_entry = None
        return await self._start_login(
            username=username,
            password=password,
            country=country,
            openudid=secrets.token_hex(8),
            retry_step="user",
            retry_schema=self._user_schema(default_country=country),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry
        current_username = entry.data[CONF_USERNAME]
        current_country = self._default_country(entry)

        if user_input is None:
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=self._user_schema(
                    default_username=current_username,
                    default_country=current_country,
                ),
            )

        username = user_input[CONF_USERNAME].strip()
        country = user_input[CONF_COUNTRY_CODE].strip().upper() or current_country

        if username != current_username:
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=self._user_schema(
                    default_username=current_username,
                    default_country=country,
                ),
                errors={CONF_USERNAME: "username_mismatch"},
            )

        self._flow_mode = "reconfigure"
        self._target_entry = entry
        openudid = entry.data.get(CONF_OPENUDID) or secrets.token_hex(8)
        return await self._start_login(
            username=username,
            password=user_input[CONF_PASSWORD],
            country=country,
            openudid=openudid,
            retry_step="reconfigure",
            retry_schema=self._user_schema(
                default_username=current_username,
                default_country=country,
            ),
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauthentication when credentials or session expire."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauth confirmation step."""
        entry = self._get_reauth_entry()
        username = entry.data[CONF_USERNAME]
        current_country = self._default_country(entry)
        schema = Schema(
            {
                Required(CONF_PASSWORD): cv.string,
                Required(CONF_COUNTRY_CODE, default=current_country): cv.string,
            }
        )

        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=schema,
                description_placeholders={"username": username},
            )

        country = user_input[CONF_COUNTRY_CODE].strip().upper() or current_country
        self._flow_mode = "reauth"
        self._target_entry = entry
        openudid = entry.data.get(CONF_OPENUDID) or secrets.token_hex(8)
        return await self._start_login(
            username=username,
            password=user_input[CONF_PASSWORD],
            country=country,
            openudid=openudid,
            retry_step="reauth_confirm",
            retry_schema=schema,
            description_placeholders={"username": username},
        )

    async def _start_login(
        self,
        *,
        username: str,
        password: str,
        country: str,
        openudid: str,
        retry_step: str,
        retry_schema: Schema,
        description_placeholders: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        session = async_get_clientsession(self.hass)
        self._pending_data = {
            CONF_USERNAME: username,
            CONF_PASSWORD: password,
            CONF_COUNTRY_CODE: country,
            CONF_OPENUDID: openudid,
        }
        self._eufy_login = EufyLogin(
            username,
            password,
            openudid,
            websession=session,
            country_code=country,
        )

        try:
            await self._eufy_login.init()
        except MegaCaptchaRequiredError as cap:
            self._captcha_image = cap.image
            return await self.async_step_captcha()
        except MegaTwoFactorRequiredError as tfa:
            self._two_factor_method = tfa.method
            return await self.async_step_two_factor()
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Eufy login failed: %s", err)
            return self.async_show_form(
                step_id=retry_step,
                data_schema=retry_schema,
                errors={"base": "invalid_auth"},
                description_placeholders=description_placeholders,
            )

        return self._finish_flow(
            retry_step=retry_step,
            retry_schema=retry_schema,
            description_placeholders=description_placeholders,
        )

    async def async_step_captcha(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Display and validate a Mega captcha challenge."""
        schema = Schema({Required("captcha_answer"): cv.string})

        if user_input is None:
            return self.async_show_form(
                step_id="captcha",
                data_schema=schema,
                description_placeholders={"captcha_image": self._captcha_image},
            )

        if self._eufy_login is None:
            return self.async_abort(reason="unknown")

        try:
            await self._eufy_login.solve_captcha(user_input["captcha_answer"])
        except MegaCaptchaRequiredError as cap:
            self._captcha_image = cap.image
            return self.async_show_form(
                step_id="captcha",
                data_schema=schema,
                errors={"base": "invalid_captcha"},
                description_placeholders={"captcha_image": self._captcha_image},
            )
        except MegaTwoFactorRequiredError as tfa:
            self._two_factor_method = tfa.method
            return await self.async_step_two_factor()
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Captcha submission failed: %s", err)
            return self.async_show_form(
                step_id="captcha",
                data_schema=schema,
                errors={"base": "invalid_auth"},
                description_placeholders={"captcha_image": self._captcha_image},
            )

        return self._finish_flow(
            retry_step="captcha",
            retry_schema=schema,
            description_placeholders={"captcha_image": self._captcha_image},
        )

    async def async_step_two_factor(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Prompt for and submit a Mega 2FA verification code."""
        schema = Schema({Required("verify_code"): cv.string})
        placeholders = {"method": self._two_factor_method}

        if user_input is None:
            return self.async_show_form(
                step_id="two_factor",
                data_schema=schema,
                description_placeholders=placeholders,
            )

        if self._eufy_login is None:
            return self.async_abort(reason="unknown")

        try:
            await self._eufy_login.submit_verify_code(user_input["verify_code"])
        except MegaApiError as err:
            _LOGGER.warning("2FA verification failed: %s", err)
            return self.async_show_form(
                step_id="two_factor",
                data_schema=schema,
                errors={"base": "invalid_code"},
                description_placeholders=placeholders,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Unexpected 2FA failure: %s", err)
            return self.async_show_form(
                step_id="two_factor",
                data_schema=schema,
                errors={"base": "invalid_auth"},
                description_placeholders=placeholders,
            )

        return self._finish_flow(
            retry_step="two_factor",
            retry_schema=schema,
            description_placeholders=placeholders,
        )

    def _finish_flow(
        self,
        *,
        retry_step: str,
        retry_schema: Schema,
        description_placeholders: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        assert self._eufy_login is not None
        devices = self._eufy_login.mqtt_devices + self._eufy_login.cloud_devices
        if not devices:
            return self.async_show_form(
                step_id=retry_step,
                data_schema=retry_schema,
                errors={"base": "no_devices"},
                description_placeholders=description_placeholders,
            )

        title = ", ".join(d.get("deviceName") or "Eufy Robot" for d in devices)
        mega_session = self._eufy_login.export_session()
        final_data = {
            **self._pending_data,
            CONF_MEGA_SESSION: mega_session,
        }

        if self._flow_mode in ("reconfigure", "reauth") and self._target_entry:
            return self.async_update_reload_and_abort(
                self._target_entry,
                data={**self._target_entry.data, **final_data},
                title=title if self._flow_mode == "reconfigure" else self._target_entry.title,
            )

        final_data[VACS] = {}
        return self.async_create_entry(title=title, data=final_data)


class OptionsFlowHandler(config_entries.OptionsFlowWithReload):
    """Eufy Robovac options: global settings + per-device local-Tuya overrides."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._selected_device: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["settings", "devices"],
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            if user_input.get(CONF_NOTIFY_MOBILE_SERVICE) is None:
                user_input[CONF_NOTIFY_MOBILE_SERVICE] = ""
            return self.async_create_entry(
                title="", data={**self._config_entry.options, **user_input}
            )

        opts = self._config_entry.options
        current_max_px = str(opts.get(CONF_MAP_MAX_PX, DEFAULT_MAP_MAX_PX))
        current_robot_style = opts.get(CONF_ROBOT_STYLE, DEFAULT_ROBOT_STYLE)
        current_notify_desktop = opts.get(CONF_NOTIFY_DESKTOP, DEFAULT_NOTIFY_DESKTOP)
        current_notify_mobile_service = opts.get(
            CONF_NOTIFY_MOBILE_SERVICE, DEFAULT_NOTIFY_MOBILE_SERVICE
        )

        all_notify = self.hass.services.async_services().get("notify", {})
        mobile_services = sorted(
            svc for svc in all_notify if svc.startswith("mobile_app_")
        )
        mobile_options = [
            selector.SelectOptionDict(
                value=svc,
                label=svc.replace("mobile_app_", "").replace("_", " ").title(),
            )
            for svc in mobile_services
        ]

        schema = Schema(
            {
                VOptional(CONF_MAP_MAX_PX, default=current_max_px): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value="256", label="256 px (low)"),
                            selector.SelectOptionDict(value="512", label="512 px (default)"),
                            selector.SelectOptionDict(value="1024", label="1024 px (high)"),
                            selector.SelectOptionDict(value="2048", label="2048 px (ultra)"),
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                VOptional(CONF_ROBOT_STYLE, default=current_robot_style): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value="googly", label="Googly Eyes"),
                            selector.SelectOptionDict(value="dot", label="Dot"),
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                VOptional(
                    CONF_NOTIFY_DESKTOP, default=current_notify_desktop
                ): selector.BooleanSelector(),
                VOptional(
                    CONF_NOTIFY_MOBILE_SERVICE, default=current_notify_mobile_service
                ): vol.Maybe(
                    selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=mobile_options,
                            custom_value=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                ),
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)

    def _eligible_devices(self) -> list[tuple[str, str, str, Any]]:
        runtime = self.hass.data.get(DOMAIN, {}).get(
            self._config_entry.entry_id, {}
        )
        coordinators = runtime.get("coordinators", []) if runtime else []
        return [
            (c.device_id, c.device_name, c.device_model, c) for c in coordinators
        ]

    async def async_step_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        devices = self._eligible_devices()
        if not devices:
            return self.async_abort(reason="no_devices")

        if user_input is not None:
            self._selected_device = user_input["device"]
            return await self.async_step_device()

        options = [
            selector.SelectOptionDict(value=dev_id, label=f"{name} ({model})")
            for dev_id, name, model, _coord in devices
        ]
        schema = Schema(
            {
                Required("device", default=options[0]["value"]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options, mode=selector.SelectSelectorMode.LIST
                    )
                )
            }
        )
        return self.async_show_form(step_id="devices", data_schema=schema)

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        dev_id = self._selected_device
        devices = {d[0]: d for d in self._eligible_devices()}
        if not dev_id or dev_id not in devices:
            return self.async_abort(reason="no_devices")
        _id, name, model, coord = devices[dev_id]
        has_local_key = bool(getattr(coord, "_local_key", None))
        existing_all: dict[str, dict] = dict(
            self._config_entry.options.get(CONF_LOCAL_DEVICES, {})
        )
        current: dict[str, Any] = dict(existing_all.get(dev_id, {}))
        map_ids_text = _format_map_ids_text(
            current.get(CONF_MAP_ID), current.get(CONF_MAP_IDS) or {}
        )
        errors: dict[str, str] = {}

        if user_input is not None:
            host = (user_input.get(CONF_LOCAL_HOST, "") or "").strip()
            version = user_input.get(CONF_LOCAL_VERSION, 3.3)
            rooms_parsed = _parse_rooms_text(
                user_input.get(CONF_ROOM_NAMES, "") or ""
            )
            map_ids_text = user_input.get(CONF_MAP_ID, "") or ""
            if host and not _is_valid_host(host):
                errors[CONF_LOCAL_HOST] = "invalid_host"
            try:
                map_id_all, map_ids = _parse_map_ids_text(map_ids_text)
            except ValueError:
                map_id_all, map_ids = None, {}
                errors[CONF_MAP_ID] = "invalid_map_id"
            if not errors:
                entry: dict[str, Any] = {}
                if host and has_local_key:
                    entry[CONF_LOCAL_HOST] = host
                    entry[CONF_LOCAL_VERSION] = float(version or 3.3)
                if rooms_parsed:
                    entry[CONF_ROOM_NAMES] = rooms_parsed
                if map_id_all is not None:
                    entry[CONF_MAP_ID] = map_id_all
                if map_ids:
                    entry[CONF_MAP_IDS] = map_ids
                if entry:
                    existing_all[dev_id] = entry
                else:
                    existing_all.pop(dev_id, None)
                return self.async_create_entry(
                    title="",
                    data={
                        **self._config_entry.options,
                        CONF_LOCAL_DEVICES: existing_all,
                    },
                )
            current = {
                CONF_LOCAL_HOST: host,
                CONF_LOCAL_VERSION: version,
                CONF_ROOM_NAMES: rooms_parsed,
            }

        schema_dict: dict[Any, Any] = {}
        if has_local_key:
            schema_dict[
                VOptional(
                    CONF_LOCAL_HOST,
                    description={"suggested_value": current.get(CONF_LOCAL_HOST, "")},
                )
            ] = cv.string
            schema_dict[
                VOptional(
                    CONF_LOCAL_VERSION, default=current.get(CONF_LOCAL_VERSION, 3.3)
                )
            ] = In([3.1, 3.3, 3.4, 3.5])
        schema_dict[
            VOptional(
                CONF_ROOM_NAMES,
                description={
                    "suggested_value": _format_rooms_text(
                        current.get(CONF_ROOM_NAMES) or {}
                    )
                },
            )
        ] = selector.TextSelector(selector.TextSelectorConfig(multiline=True))
        schema_dict[
            VOptional(CONF_MAP_ID, description={"suggested_value": map_ids_text})
        ] = selector.TextSelector(selector.TextSelectorConfig(multiline=True))
        return self.async_show_form(
            step_id="device",
            data_schema=Schema(schema_dict),
            description_placeholders={"device": f"{name} ({model})"},
            errors=errors,
        )


def _option_lines(text: str) -> list[str]:
    lines = (raw_line.strip() for raw_line in text.splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def _parse_rooms_text(text: str) -> dict[int, str]:
    rooms: dict[int, str] = {}
    for line in _option_lines(text):
        if ":" not in line:
            continue
        id_part, _, name_part = line.partition(":")
        try:
            room_id = int(id_part.strip())
        except ValueError:
            continue
        name = name_part.strip()
        if name:
            rooms[room_id] = name
    return rooms


_HOSTNAME_LABEL = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")


def _is_valid_host(host: str) -> bool:
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    if len(host) > 253:
        return False
    return all(_HOSTNAME_LABEL.match(label) for label in host.split("."))


def _format_rooms_text(rooms: dict[int, str]) -> str:
    if not rooms:
        return ""
    return "\n".join(
        f"{rid}: {name}"
        for rid, name in sorted(rooms.items(), key=lambda kv: int(kv[0]))
    )


def _parse_map_ids_text(text: str) -> tuple[int | None, dict[int, int]]:
    all_maps: int | None = None
    per_map: dict[int, int] = {}
    for line in _option_lines(text):
        reported_part, separator, local_part = line.partition(":")
        if separator:
            per_map[_positive_int(reported_part)] = _positive_int(local_part)
        else:
            all_maps = _positive_int(line)
    return all_maps, per_map


def _positive_int(text: str) -> int:
    value = int(text.strip())
    if value <= 0:
        raise ValueError(f"not a positive integer: {text!r}")
    return value


def _format_map_ids_text(all_maps: int | None, per_map: dict[int, int]) -> str:
    lines = [str(all_maps)] if all_maps else []
    lines.extend(
        f"{reported_id}: {local_id}"
        for reported_id, local_id in sorted(
            per_map.items(), key=lambda kv: int(kv[0])
        )
    )
    return "\n".join(lines)
