"""Serve the dashboard assets installed with the integration by HACS."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig

from .const import DOMAIN

ASSET_DIRECTORY = Path(__file__).parent / "frontend"
ASSET_URL = "/ev_charge_controller_static"


def _asset_fingerprint() -> str:
    """Invalidate browser module caches whenever either JS asset changes."""
    digest = sha256()
    for name in ("ev-charge-dashboard.js", "ev-charge-controller-card.js"):
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
