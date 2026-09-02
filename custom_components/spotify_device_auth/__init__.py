"""The Spotify Device Auth integration.

Logs a Spotify account into Spotify Connect speakers via the Zeroconf
username/password "default" blob flow, so a device shows up in the regular
Spotify app. Exposes services callable from scripts/automations.
"""

from __future__ import annotations

import asyncio
import logging

import voluptuous as vol
from homeassistant.components import zeroconf as ha_zeroconf
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from . import zeroconf_login as zcl
from .const import (
    CONF_ACCOUNT,
    CONF_ACCOUNT_ID,
    CONF_CONTEXT_URI,
    CONF_CPATH,
    CONF_DEVICE_ID,
    CONF_TIMEOUT,
    CONF_URIS,
    CONF_VERSION,
    DEFAULT_DISCOVERY_TIMEOUT,
    DEFAULT_VERSION,
    DOMAIN,
    PLAY_RETRY_ATTEMPTS,
    PLAY_RETRY_DELAY,
    SERVICE_DISCOVER,
    SERVICE_LOGIN,
    SERVICE_LOGOUT,
    SERVICE_PLAY,
    SPOTIFY_DOMAIN,
    SPOTIFY_PLAY_URL,
)

_LOGGER = logging.getLogger(__name__)

_DEVICE_FIELDS = {
    vol.Required(CONF_HOST): cv.string,
    vol.Optional(CONF_PORT): cv.port,
    vol.Optional(CONF_CPATH): cv.string,
    vol.Optional(CONF_VERSION): cv.string,
}
LOGIN_SCHEMA = vol.Schema({**_DEVICE_FIELDS, vol.Optional(CONF_ACCOUNT): cv.string})
LOGOUT_SCHEMA = vol.Schema(_DEVICE_FIELDS)
DISCOVER_SCHEMA = vol.Schema(
    {vol.Optional(CONF_TIMEOUT, default=DEFAULT_DISCOVERY_TIMEOUT): vol.Coerce(float)}
)
PLAY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Exclusive(CONF_CONTEXT_URI, "what"): cv.string,
        vol.Exclusive(CONF_URIS, "what"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_ACCOUNT): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's services (independent of config entries)."""

    async def _resolve_uri(call: ServiceCall) -> tuple[str, str]:
        """Build the device URI, resolving port/cpath/version via mDNS if missing."""
        host: str = call.data[CONF_HOST]
        port = call.data.get(CONF_PORT)
        cpath = call.data.get(CONF_CPATH)
        version = call.data.get(CONF_VERSION) or DEFAULT_VERSION
        if port is None or cpath is None:
            zc = await ha_zeroconf.async_get_instance(hass)
            devices = await hass.async_add_executor_job(
                zcl.discover, zc, DEFAULT_DISCOVERY_TIMEOUT
            )
            match = next(
                (
                    d
                    for d in devices
                    if host in d["addresses"] or host.lower() in d["name"].lower()
                ),
                None,
            )
            if match is None:
                raise ServiceValidationError(
                    f"Could not find Spotify Connect device '{host}' via mDNS; "
                    "pass port and cpath explicitly"
                )
            port = port or match["port"]
            cpath = cpath or match["cpath"]
            version = match["version"] or version
        return f"http://{host}:{port}{cpath}", version

    def _select_entry(account: str | None) -> ConfigEntry:
        """Pick the account config entry by name, or the only one configured."""
        entries = hass.config_entries.async_entries(DOMAIN)
        loaded = [e for e in entries if e.state is ConfigEntryState.LOADED]
        entries = loaded or entries
        if not entries:
            raise ServiceValidationError("No Spotify Device Auth account configured")
        if account:
            for entry in entries:
                if account.lower() in (
                    entry.title.lower(),
                    (entry.unique_id or "").lower(),
                ):
                    return entry
            raise ServiceValidationError(f"No account named '{account}'")
        if len(entries) > 1:
            names = ", ".join(sorted(e.title for e in entries))
            raise ServiceValidationError(
                f"Multiple accounts configured ({names}); specify 'account'"
            )
        return entries[0]

    async def handle_login(call: ServiceCall) -> ServiceResponse:
        entry = _select_entry(call.data.get(CONF_ACCOUNT))
        uri, version = await _resolve_uri(call)
        session = async_get_clientsession(hass)
        try:
            info = await zcl.async_get_info(session, uri, version)
            result = await zcl.async_add_user(
                session,
                uri,
                version,
                entry.data[CONF_USERNAME],
                entry.data[CONF_PASSWORD],
                entry.data[CONF_ACCOUNT_ID],
                info,
            )
        except Exception as err:  # noqa: BLE001 - surface as a HA service error
            raise HomeAssistantError(f"Spotify Connect login failed: {err}") from err
        if str(result.get("status")) != "101":
            raise HomeAssistantError(f"Spotify Connect addUser failed: {result}")
        _LOGGER.debug(
            "Logged %s into %s [%s %s id=%s]",
            entry.title,
            call.data[CONF_HOST],
            info.get("brandDisplayName"),
            info.get("modelDisplayName"),
            info.get("deviceID"),
        )
        return {
            "id": info.get("deviceID"),
            "name": info.get("remoteName") or None,
            "brand": info.get("brandDisplayName"),
            "model": info.get("modelDisplayName"),
            "result": result,
        }

    async def handle_logout(call: ServiceCall) -> ServiceResponse:
        uri, version = await _resolve_uri(call)
        session = async_get_clientsession(hass)
        try:
            result = await zcl.async_reset_users(session, uri, version)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"Spotify Connect logout failed: {err}") from err
        return {"result": result}

    async def handle_discover(call: ServiceCall) -> ServiceResponse:
        zc = await ha_zeroconf.async_get_instance(hass)
        devices = await hass.async_add_executor_job(
            zcl.discover, zc, call.data[CONF_TIMEOUT]
        )
        return {"devices": devices}

    def _spotify_entry(account: str | None) -> ConfigEntry:
        """Pick the core Spotify integration entry whose OAuth token we borrow."""
        entries = hass.config_entries.async_entries(SPOTIFY_DOMAIN)
        loaded = [e for e in entries if e.state is ConfigEntryState.LOADED]
        entries = loaded or entries
        if not entries:
            raise ServiceValidationError("The Spotify integration is not set up")
        if account:
            for entry in entries:
                if account.lower() in (
                    entry.title.lower(),
                    (entry.unique_id or "").lower(),
                ):
                    return entry
            raise ServiceValidationError(f"No Spotify account named '{account}'")
        if len(entries) > 1:
            names = ", ".join(sorted(e.title for e in entries))
            raise ServiceValidationError(
                f"Multiple Spotify accounts ({names}); specify 'account'"
            )
        return entries[0]

    async def handle_play(call: ServiceCall) -> ServiceResponse:
        """Start playback on a device via the Spotify Web API.

        Reuses the core Spotify integration's OAuth token (auto-refreshed), so
        no credentials live here. Unlike media_player.select_source this can
        cold-start an idle device by targeting it with ?device_id=.
        """
        device_id: str = call.data[CONF_DEVICE_ID]
        context_uri: str | None = call.data.get(CONF_CONTEXT_URI)
        uris: list[str] | None = call.data.get(CONF_URIS)
        if not context_uri and not uris:
            raise ServiceValidationError("Provide either 'context_uri' or 'uris'")

        entry = _spotify_entry(call.data.get(CONF_ACCOUNT))
        implementation = (
            await config_entry_oauth2_flow.async_get_config_entry_implementation(
                hass, entry
            )
        )
        oauth = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)

        body: dict = {"context_uri": context_uri} if context_uri else {"uris": uris}
        url = f"{SPOTIFY_PLAY_URL}?device_id={device_id}"

        last = ""
        for attempt in range(PLAY_RETRY_ATTEMPTS):
            resp = await oauth.async_request("PUT", url, json=body)
            if resp.status in (200, 202, 204):
                _LOGGER.debug("Started playback on %s (status %s)", device_id, resp.status)
                return {"status": resp.status, "device_id": device_id}
            last = f"{resp.status}: {(await resp.text()).strip()}"
            # 404 = device not registered with Spotify yet (just logged in); retry.
            if resp.status != 404:
                break
            await asyncio.sleep(PLAY_RETRY_DELAY)
        raise HomeAssistantError(f"Spotify play failed ({last})")

    hass.services.async_register(
        DOMAIN, SERVICE_LOGIN, handle_login, schema=LOGIN_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_LOGOUT, handle_logout, schema=LOGOUT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DISCOVER, handle_discover, schema=DISCOVER_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_PLAY, handle_play, schema=PLAY_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Spotify account from a config entry (credentials live in entry.data)."""
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return True
