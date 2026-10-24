# Migration and rollback

## Manual installation to HACS

Add the repository to HACS as an Integration, download the update and restart Home Assistant. The integration domain, unique IDs and saved config entries remain the same. HACS manages the same component directory, so do not remove and recreate the integration. Keep the previous component folder if you want a manual rollback.

The integration now registers the EV Charging sidebar panel at `/ev-charging` automatically. Overview and Schedule are available without creating a dashboard or registering Lovelace resources. After an HACS update, restart Home Assistant and refresh the browser so the updated panel code loads.

Existing Lovelace dashboards and saved YAML are retained. If you previously installed the older standalone frontend, its manually registered `/local/ev-charge-controller/` resources can be removed from Settings → Dashboards → Resources after confirming that no custom dashboard still uses them. The optional [legacy dashboard example](examples/dashboard.yaml) remains available for custom Lovelace layouts.

## Other charging controllers

Keep Monitoring only enabled while comparing decisions with real data. Identify existing automations, scripts and provider features operating the same switch. Choose an owner for each tariff and avoid competing active controllers. Make production automation changes yourself, then check start, stop, manual override and tariff handover before relying on it.

On another or unknown tariff the integration releases control without operating the switch; it does not enable another system. Automatic control off also leaves observed charging unchanged, rather than stopping it.

To roll back, select a previous HACS version or restore the previous component folder, restart Home Assistant and restore your earlier charging arrangement yourself.
