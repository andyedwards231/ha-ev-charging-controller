# Entity connections

Use the setup selectors to choose actual entities from your existing integrations. IDs vary by installation.

| Field | Expected source |
| --- | --- |
| Charging switch | Tessie's charging control switch. |
| Charging feedback | Binary sensor for active charging, separate from the switch. |
| Charge cable | Binary sensor for physical connection. |
| Location and home zone | Vehicle tracker and the zone where control is allowed. |
| Battery | Sensor reporting 0–100%. |
| Car limit | Requested percentage limit, used read-only. |
| Current | Requested charging amps, rather than instantaneous battery current. |
| Current rate | Octopus Energy import price with current start/end and tariff attributes. |
| Published rates | Octopus Energy event entities containing `rates`; tomorrow is optional. |
| Tariff and units | Normally attribute `tariff`, match `AGILE`; choose actual `GBP/kWh` or `p/kWh` units. |
| Free session | Optional calendar containing confirmed start/end times. |
| Measured power | Optional grid-side charger power in W or kW. |
| Preconditioning | Optional binary sensor for existing preconditioning. |
| Completion | Optional sensor and the exact state meaning complete. |

Requested current times configured voltage estimates grid power: 24 A at an assumed 230 V is 5.52 kW before losses. The current code assumes single-phase AC.

Configure edits model and control preferences; Reconfigure changes entity connections. Review capacity, voltage, efficiency and margin. Leave power learning off until the measurement source is understood.

Initial cheap rate is 12p/kWh and planner target is 80%. Shared helpers are not changed. Start in Monitoring only and inspect Status, Charging plan and shortfall. The car's own limit remains authoritative.

Ready-by values use Home Assistant's configured time zone. Ambiguous or nonexistent clock-change times require an explicit offset. Other modes ignore the stored deadline.

The Schedule tab saves request values together. The same `ev_charge_controller.set_request` action is available in Developer Tools. No additional credentials or administrator token are required.
