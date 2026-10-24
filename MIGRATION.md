# Migration and rollback

## Manual installation to HACS

Add the repository as an Integration, download and restart Home Assistant. The domain and unique IDs remain the same; config entries and saved preferences are retained. Keep the previous component folder if you want a manual rollback.

Dashboard code now lives under `custom_components/ev_charge_controller/frontend/`. The integration serves and loads it without editing Lovelace configuration. HACS updates Python and frontend files together. Create or update the dashboard once using [the example](examples/dashboard.yaml).

After switching, older manually registered `/local/ev-charge-controller/` resources can be removed from Settings → Dashboards → Resources. Existing compact-card dashboards can load `/ev_charge_controller_static/ev-charge-controller-card.js` manually instead. The new Schedule page uses its own bundled control element and does not depend on an older registered card.

HACS retains saved dashboard YAML. Changes to the example layout may need a manual edit. Bundled JavaScript URLs are fingerprinted at startup, so updated code loads after restart and browser refresh.

## Other charging controllers

Keep Monitoring only enabled while comparing decisions with real data. Identify existing automations, scripts and provider features operating the same switch. Choose an owner for each tariff and avoid competing active controllers. Make production automation changes yourself, then check start, stop, manual override and tariff handover before relying on it.

On another or unknown tariff the integration releases control without operating the switch; it does not enable another system. Automatic control off also leaves observed charging unchanged, rather than stopping it.

To roll back, select a previous HACS version or restore the previous component folder, restart Home Assistant and restore your earlier charging arrangement yourself.
