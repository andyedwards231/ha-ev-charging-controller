"""Bundled frontend registration without a live HTTP server or Lovelace writes."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from ev_charge_controller import frontend
from ev_charge_controller.const import DOMAIN


@pytest.mark.asyncio
async def test_frontend_assets_are_registered_once_and_fingerprinted(monkeypatch):
    hass = SimpleNamespace(
        data={},
        http=SimpleNamespace(async_register_static_paths=AsyncMock()),
        async_add_executor_job=AsyncMock(return_value="test-digest"),
    )
    add_js = Mock()
    monkeypatch.setattr(frontend.frontend, "add_extra_js_url", add_js)
    await frontend.async_setup_frontend(hass)
    await frontend.async_setup_frontend(hass)

    hass.http.async_register_static_paths.assert_awaited_once()
    path = hass.http.async_register_static_paths.call_args.args[0][0]
    assert path.url_path == "/ev_charge_controller_static"
    assert path.cache_headers is False
    assert path.path == str(frontend.ASSET_DIRECTORY)
    add_js.assert_called_once_with(
        hass, "/ev_charge_controller_static/ev-charge-dashboard.js?v=test-digest"
    )
    assert hass.data[DOMAIN]["frontend_registered"] is True


def test_fingerprint_changes_with_any_asset_and_assets_stay_inside_component(tmp_path, monkeypatch):
    assert frontend.ASSET_DIRECTORY.parent.name == DOMAIN
    assert (frontend.ASSET_DIRECTORY / "icon.png").is_file()
    for name in frontend._ASSET_FILES:
        (tmp_path / name).write_text("original")
    monkeypatch.setattr(frontend, "ASSET_DIRECTORY", tmp_path)
    original = frontend._asset_fingerprint()
    (tmp_path / "ev-charge-dashboard.js").write_text("changed")
    dashboard_changed = frontend._asset_fingerprint()
    (tmp_path / "ev-charge-controller-card.js").write_text("changed")
    card_changed = frontend._asset_fingerprint()
    (tmp_path / "ev-charge-panel.js").write_text("changed")
    panel_changed = frontend._asset_fingerprint()
    assert len({original, dashboard_changed, card_changed, panel_changed}) == 4


@pytest.mark.asyncio
async def test_native_panel_registers_once_for_multiple_entries_and_removes_after_last(monkeypatch):
    hass = SimpleNamespace(
        data={},
        async_add_executor_job=AsyncMock(return_value="panel-digest"),
    )
    register = AsyncMock()
    remove = Mock()
    monkeypatch.setattr(frontend.panel_custom, "async_register_panel", register)
    monkeypatch.setattr(frontend.frontend, "async_remove_panel", remove)

    await frontend.async_setup_panel(hass, "entry-a")
    await frontend.async_setup_panel(hass, "entry-a")
    await frontend.async_setup_panel(hass, "entry-b")

    register.assert_awaited_once_with(
        hass,
        frontend_url_path="ev-charging",
        webcomponent_name="ev-charge-panel",
        sidebar_title="EV Charging",
        sidebar_icon="mdi:car-electric",
        module_url="/ev_charge_controller_static/ev-charge-panel.js?v=panel-digest",
        embed_iframe=False,
        require_admin=False,
        config={"domain": DOMAIN},
    )
    assert hass.data[DOMAIN]["panel_entries"] == {"entry-a", "entry-b"}

    frontend.async_unload_panel_entry(hass, "entry-a")
    remove.assert_not_called()
    frontend.async_unload_panel_entry(hass, "entry-b")
    remove.assert_called_once_with(hass, "ev-charging")
    assert "panel_entries" not in hass.data[DOMAIN]
    assert not hass.data[DOMAIN].get("panel_registered", False)


@pytest.mark.asyncio
async def test_panel_registration_failure_does_not_claim_entry_or_remove_existing_panel(monkeypatch):
    hass = SimpleNamespace(data={}, async_add_executor_job=AsyncMock(return_value="digest"))
    register = AsyncMock(side_effect=RuntimeError("panel registration failed"))
    remove = Mock()
    monkeypatch.setattr(frontend.panel_custom, "async_register_panel", register)
    monkeypatch.setattr(frontend.frontend, "async_remove_panel", remove)

    with pytest.raises(RuntimeError, match="panel registration failed"):
        await frontend.async_setup_panel(hass, "entry-a")

    assert hass.data[DOMAIN].get("panel_entries", set()) == set()
    assert not hass.data[DOMAIN].get("panel_registered", False)
    remove.assert_not_called()


@pytest.mark.asyncio
async def test_concurrent_entry_setup_registers_panel_once(monkeypatch):
    hass = SimpleNamespace(data={}, async_add_executor_job=AsyncMock(return_value="digest"))
    active_registrations = 0
    max_active_registrations = 0

    async def register(*args, **kwargs):
        nonlocal active_registrations, max_active_registrations
        active_registrations += 1
        max_active_registrations = max(max_active_registrations, active_registrations)
        await asyncio.sleep(0)
        active_registrations -= 1

    register_panel = AsyncMock(side_effect=register)
    monkeypatch.setattr(frontend.panel_custom, "async_register_panel", register_panel)

    await asyncio.gather(
        frontend.async_setup_panel(hass, "entry-a"),
        frontend.async_setup_panel(hass, "entry-b"),
    )

    register_panel.assert_awaited_once()
    assert max_active_registrations == 1
    assert hass.data[DOMAIN]["panel_entries"] == {"entry-a", "entry-b"}
