# Verification

Local checks use Home Assistant 2026.10.0, Python 3.14, memory-only storage replacements and mocked charging services. They do not connect to production Home Assistant or operate a vehicle.

Python tests cover planning, partial and invalid rates, gaps, overlaps, clock changes, current-amp changes, learned power, forecasts and caching. Existing checks cover monitoring, tariff handover, boost, overrides, completion latches, retries, config flows and lifecycle cleanup. Bundled frontend registration is tested without Lovelace writes.

Frontend checks use simulated entities and actions. They cover atomic saves, entity scoping, rejected requests, retained drafts, feedback, forecasts, missing metrics, completion times, escaping, unrelated-state render suppression and responsive layouts down to 320px. Desktop dark and mobile light previews are inspected locally.

CI validates before release. The archive contains runtime assets and public documentation, excluding development environments, caches, tests and private configuration.

These checks do not prove physical charging, production frontend behaviour or model accuracy for a particular vehicle. Capacity, voltage, efficiency and margin remain assumptions. Production CPU and Recorder storage have not been benchmarked.
