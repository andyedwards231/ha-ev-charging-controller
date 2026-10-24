"""Bundled frontend registration without a live HTTP server or Lovelace writes."""

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


def test_fingerprint_changes_with_either_asset_and_assets_stay_inside_component(tmp_path, monkeypatch):
    assert frontend.ASSET_DIRECTORY.parent.name == DOMAIN
    assert (frontend.ASSET_DIRECTORY / "icon.png").is_file()
    for name in ("ev-charge-dashboard.js", "ev-charge-controller-card.js"):
        (tmp_path / name).write_text("original")
    monkeypatch.setattr(frontend, "ASSET_DIRECTORY", tmp_path)
    original = frontend._asset_fingerprint()
    (tmp_path / "ev-charge-dashboard.js").write_text("changed")
    dashboard_changed = frontend._asset_fingerprint()
    (tmp_path / "ev-charge-controller-card.js").write_text("changed")
    assert len({original, dashboard_changed, frontend._asset_fingerprint()}) == 3
