# EV Charge Controller

A Home Assistant integration for tariff-aware EV charging using existing Octopus Energy and Tesla/Tessie entities. It plans around published prices, follows the car's requested charging current and explains why it is charging or waiting.

**Requires Home Assistant 2026.10.0 or later.** The default is monitoring only: decisions are calculated without operating the charging switch. Existing provider integrations handle cloud connectivity; no additional credentials are required.

## Features

| Mode | Behaviour |
| --- | --- |
| Cheap top-up | Charge whenever the valid live rate is below your maximum, up to the car's limit. |
| Charge by deadline | Choose the cheapest published periods needed for a battery target and ready-by time. |
| Flexible target | Reach and maintain a battery target using eligible cheap periods, without a deadline. |

After installation through HACS and a Home Assistant restart, the integration registers an **EV Charging** panel in the sidebar at `/ev-charging`. It has Overview and Schedule tabs and discovers entities from the selected integration entry, including installations with more than one configured vehicle. No Lovelace YAML or manual dashboard setup is required. See [the dashboard guide](docs/dashboard.md).

Overview shows current battery and charging feedback, conditional battery and cost forecasts, published prices and charging windows. Schedule saves the mode, target, ready-by time, maximum cheap rate and hard ceiling together. It also shows the requested current reported by Tesla/Tessie; change current in the vehicle integration. Boost is a separate immediate action, with automatic pause, resume and monitoring controls alongside it.

Missing future prices leave a provisional plan using valid published intervals. It warns about incomplete coverage and replans as rates arrive. Unknown periods are never treated as free electricity. A target above the car's limit is reported without changing that limit.

Tesla/Tessie's requested amps determine charging speed. Lower current produces a longer plan. The integration never changes current, charge limit or climate settings. Optional measured-power learning scales with the current setting.

## Install with HACS

1. Add `https://github.com/andyedwards231/ha-ev-charging-controller` under HACS **Custom repositories**, with type **Integration**.
2. Download **EV Charge Controller** and restart Home Assistant.
3. Open **Settings → Devices & services → Add integration → EV Charge Controller**. Select your existing vehicle and tariff entities using [SETUP.md](SETUP.md).
4. Keep **Monitoring only** enabled while checking the plan and observed feedback.
5. Open **EV Charging** in the sidebar. If Home Assistant was already open, refresh the browser after the restart.

[Add this repository to HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=andyedwards231&repository=ha-ev-charging-controller&category=integration)

The repository must be public for HACS. New published releases appear as updates. After installing an update, restart Home Assistant and refresh the browser to load the updated panel. Saved integration settings are retained. An optional legacy Lovelace configuration remains available in [examples/dashboard.yaml](examples/dashboard.yaml) for users who prefer to place the card on their own dashboards.

For an existing manual installation, HACS manages the same component directory and domain. Do not remove and recreate the integration. See [migration](MIGRATION.md).

The configured controller appears under **Settings → Devices & services → Integrations → EV Charge Controller**. Versions up to 0.3.0 classified it as a Helper, which hid it from the Integrations tab; update to 0.3.1 or later and restart Home Assistant to correct this. The existing controller and its settings are retained.

For manual installation, copy the release archive's `custom_components/ev_charge_controller` folder into your configuration's `custom_components` folder and restart Home Assistant. Copy only this integration folder.

## Model and control

Defaults assume 60 kWh usable capacity, 230 V, 92% efficiency and a 10% planning margin. These are editable model assumptions. A configured current entity supplies requested amps; otherwise fixed power is used. The current model assumes single-phase AC charging.

Deadline mode may exceed the normal cheap-rate ceiling unless the hard ceiling is enabled. Insufficient eligible periods produce a visible shortfall. Completed deadline requests remain complete until changed; flexible mode uses a restart margin. Missing or expired live prices prevent new price-based starts.

Boost temporarily bypasses price and slots within home, cable, tariff and vehicle checks. It ends at completion, cancellation, unplugging or timeout. Preconditioning is observed, rather than scheduled, with optional bounded charging exceptions.

The managed-tariff match defaults to `AGILE`. Other or unknown tariffs release control without operating the switch. This does not enable another controller. By default an unrequested charge start is stopped; a confirmed repeated start within two minutes, or a manual stop after charging is confirmed, creates a temporary hold. Resume clears it.

While a start is awaiting confirmation, Tessie can briefly report the old off state. Those reports do not create a hold, and bounded start retries remain active. An app or vehicle stop during this interval cannot be distinguished from an old report. An explicit Home Assistant user stop still creates a hold immediately. Turning Automatic control off cancels pending commands and leaves the observed charging state unchanged.

Automatic control off leaves observed charging unchanged. Monitoring only sends no charging commands. Active commands use bounded retries and require observed feedback; service acknowledgement is not confirmation. Review [migration](MIGRATION.md) before enabling active control alongside another charging arrangement.

## Efficiency and forecasts

There are no direct cloud requests. The panel accepts relevant Home Assistant state updates and renders only when its selected entries change. Charts use cached, bounded forecasts with no added history queries, polling or car requests. The backend uses event and boundary updates plus a 30-second reconciliation timer. Forecast arrays are cached, bounded to seven days and 400 points/intervals, and appear only on the plan entity. Active projections refresh within five minutes; changed battery, rates and settings are reflected immediately.

Forecast cost means remaining estimated grid electricity, including losses and margin. It excludes previously used energy and standing charges. Disconnection, monitoring, pauses and overrides are labelled as conditional forecasts.

## Development and releases

```sh
uv sync --extra dev
uv run pytest
uv run ruff check custom_components tests package.py
npm ci
npx playwright install --with-deps chromium
npm test
uv run python package.py
```

CI runs Python and frontend tests, Hassfest and HACS validation. Update manifest and project versions, then publish a `v<version>` tag or run the Release workflow. It validates first, checks the tag and builds a versioned archive. See [verification](VERIFICATION.md) for the verification scope and limits.
