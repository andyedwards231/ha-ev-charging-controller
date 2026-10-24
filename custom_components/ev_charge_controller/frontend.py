"""Serve the dashboard assets installed with the integration by HACS."""

from __future__ import annotations

import asyncio
from hashlib import sha256
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig

from .const import DOMAIN

ASSET_DIRECTORY = Path(__file__).parent / "frontend"
ASSET_URL = "/ev_charge_controller_static"
PANEL_PATH = "ev-charging"
PANEL_COMPONENT = "ev-charge-panel"
_ASSET_FILES = (
    "ev-charge-dashboard.js",
    "ev-charge-controller-card.js",
    "ev-charge-panel.js",
)


def _asset_fingerprint() -> str:
    """Invalidate browser module caches whenever any bundled JS asset changes."""
    digest = sha256()
    for name in _ASSET_FILES:
        digest.update((ASSET_DIRECTORY / name).read_bytes())
    return digest.hexdigest()[:16]


async def async_setup_frontend(hass) -> None:
    """Register static code once, without editing any Lovelace configuration."""
    shared = hass.data.setdefault(DOMAIN, {})
    if shared.get("frontend_registered"):
        return
    fingerprint = await hass.async_add_executor_job(_asset_fingerprint)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(ASSET_URL, str(ASSET_DIRECTORY), False)]
    )
    frontend.add_extra_js_url(
        hass, f"{ASSET_URL}/ev-charge-dashboard.js?v={fingerprint}"
    )
    shared["frontend_registered"] = True


async def async_setup_panel(hass, entry_id: str) -> None:
    """Register the integration-owned panel when its first entry is ready."""
    shared = hass.data.setdefault(DOMAIN, {})
    lock = shared.setdefault("panel_lock", asyncio.Lock())
    async with lock:
        loaded_entries = shared.setdefault("panel_entries", set())
        if entry_id in loaded_entries:
            return
        if not shared.get("panel_registered"):
            fingerprint = await hass.async_add_executor_job(_asset_fingerprint)
            await panel_custom.async_register_panel(
                hass,
                frontend_url_path=PANEL_PATH,
                webcomponent_name=PANEL_COMPONENT,
                sidebar_title="EV Charging",
                sidebar_icon="mdi:car-electric",
                module_url=f"{ASSET_URL}/ev-charge-panel.js?v={fingerprint}",
                embed_iframe=False,
                require_admin=False,
                config={"domain": DOMAIN},
            )
            shared["panel_registered"] = True
        loaded_entries.add(entry_id)


def async_unload_panel_entry(hass, entry_id: str) -> None:
    """Remove the panel only after its final loaded integration entry unloads."""
    shared = hass.data.get(DOMAIN, {})
    loaded_entries = shared.get("panel_entries")
    if not loaded_entries or entry_id not in loaded_entries:
        return
    loaded_entries.remove(entry_id)
    if loaded_entries:
        return
    shared.pop("panel_entries", None)
    if shared.pop("panel_registered", False):
        frontend.async_remove_panel(hass, PANEL_PATH)
