# EV Charging dashboard

The dashboard ships with the integration. No separate frontend HACS repository, `www` copy or manual resource registration is needed.

## One-time setup

1. Install the integration and restart Home Assistant.
2. Create an empty dashboard under Settings → Dashboards, named EV Charging, with an address such as `ev-charging` and sidebar access enabled.
3. Paste [examples/dashboard.yaml](../examples/dashboard.yaml) into its raw configuration editor.
4. Check the entity IDs against your controller's device page. The example uses default controller names; select your actual entities if they differ.
5. Save and refresh the browser.

Overview and Schedule are native tabs using full-width panel views. The integration loads the dashboard module at startup. Scheduling discovers related controls and the integration entry from the selected Status sensor.

## Forecasts

Battery and cost curves start from the current reading and use configured efficiency and margin. Cost is remaining estimated grid electricity, excluding previous consumption and standing charges. Negative prices can make cost fall.

Target modes follow selected known-price windows. Cheap top-up forecasts eligible published periods chronologically up to the car limit, without changing its live-price policy. Green strips show forecast charging; tables give exact times and prices.

Unknown periods stay blank. The battery forecast is labelled at the available horizon, which may be earlier than the deadline. Sufficient known slots can produce a provisional finish estimate; insufficient slots leave completion unknown.

Forecasts assume the car is home and connected for the windows. Monitoring, pauses, disconnection, away, manual hold and boost are labelled. During boost the charts show the saved price-based request. Completed deadlines and satisfied flexible maintenance stay flat until the relevant request or maintenance state changes.

## Scheduling and updates

Choose a mode, target, rate and ready-by time where applicable. Apply saves fields together. Boost applies immediately within the controller's safety checks. Requested current comes from Tesla/Tessie; change it there and the plan recalculates. The integration does not change amps or the car limit.

HACS updates integration and dashboard code together. Restart Home Assistant and refresh the browser. Saved dashboard YAML is retained; example layout changes may need manual application.

There are no extra car requests, history queries or frontend polling loops. Unrelated state changes do not rebuild Overview. Forecast arrays are cached and bounded. Optionally exclude your Charging plan sensor from Recorder if you do not want historical snapshots of its attributes.

For a local simulated preview, serve the repository with `python -m http.server` and open `/tests/frontend/preview.html`. It has no Home Assistant connection; its extra toolbar is only for testing.
