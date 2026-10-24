# EV Charging panel

After the integration is installed and Home Assistant is restarted, EV Charging appears in the sidebar at `/ev-charging`. It is a native Home Assistant panel with Overview and Schedule tabs. There is no dashboard to create, YAML to paste, or Lovelace resource to register.

The panel discovers entities by registry and scopes them to the integration entry you select. This supports installations with multiple configured vehicles without embedding vehicle-specific entity IDs in the panel. Select another entry to view its vehicle and tariff setup.

## Overview

Overview uses a dark slate and teal presentation, and also supports Home Assistant's light theme. It shows current state of charge, charging feedback and published price windows, with conditional battery, cost and price charts when forecast data is available. Charging windows are labelled with their status and price. The forecast uses the integration's cached, bounded plan data.

Battery and cost curves start from the current reading and use configured efficiency and margin. Cost is remaining estimated grid electricity, excluding previous consumption and standing charges. Negative prices can make cost fall.

Target modes follow selected known-price windows. Cheap top-up forecasts eligible published periods chronologically up to the car limit, without changing its live-price policy. Green strips show forecast charging; tables give exact times and prices.

Unknown periods stay blank. The battery forecast is labelled at the available horizon, which may be earlier than the deadline. Sufficient known slots can produce a provisional finish estimate; insufficient slots leave completion unknown.

Forecasts assume the car is home and connected for the windows. Monitoring, pauses, disconnection, away, manual hold and boost are labelled. During boost the charts show the saved price-based request. Completed deadlines and satisfied flexible maintenance stay flat until the relevant request or maintenance state changes.

## Schedule and controls

Choose Cheap top-up, Charge by deadline or Flexible target. The schedule includes target, ready-by time, maximum cheap rate and an optional hard rate ceiling. The hard ceiling prevents deadline charging above that rate. Saving applies the request fields together; Reset drafts restores the saved request values.

Requested charging amps are read from Tesla/Tessie and displayed without controls to change them. Change current in the vehicle integration; the plan recalculates from its updates. The integration does not change amps or the car limit.

Boost is a separate immediate action subject to the controller's safety checks. Automatic pause and resume, monitoring-only and automatic-control controls are shown separately from the schedule. These states affect the forecast and command behaviour as described by the integration.

## Updates and optional Lovelace example

HACS updates integration and panel code together. Install the update, restart Home Assistant and refresh the browser to load the new panel code. Integration settings and any existing Lovelace YAML are retained.

The integration discovers entities from Home Assistant's entity registry and listens for updates to relevant states. It adds no frontend polling, history queries or car requests. Unrelated state changes do not rebuild the panel. Forecast arrays are bounded and cached by the integration. Optionally exclude your Charging plan sensor from Recorder if you do not want historical snapshots of its attributes.

For users who want to place a card on a custom Lovelace dashboard, [examples/dashboard.yaml](../examples/dashboard.yaml) is an optional legacy example. It uses the bundled card and default entity IDs; update those IDs for your installation. The native sidebar panel does not depend on this YAML.

For a local simulated preview, serve the repository with `python -m http.server` and open `/tests/frontend/panel-preview.html`. It has no Home Assistant connection; its extra toolbar is only for development. The optional legacy card preview remains at `/tests/frontend/preview.html`.
