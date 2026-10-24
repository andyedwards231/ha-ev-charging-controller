# Verification

Local checks use Home Assistant 2026.10.0, Python 3.14, memory-only storage replacements and mocked charging services. They do not connect to production Home Assistant or operate a vehicle.

Python tests cover planning, partial and invalid rates, gaps, overlaps, clock changes, current-amp changes, learned power, forecasts and caching. Existing checks cover monitoring, tariff handover, boost, overrides, completion latches, retries, config flows and lifecycle cleanup. Bundled frontend registration is tested without Lovelace writes.

Command-dispatch regressions check that malformed rates stop controller-owned target charging and that a completed deadline request stays stopped after the battery level falls. The immediate input recheck uses the same control rules as the published decision; invalid planner data does not grant command authority over an unowned charge.

Start-feedback regressions simulate Tessie's optimistic switch update followed by an old cloud report, then real charging confirmation. That transient off report must not create a manual hold; explicit Home Assistant user stops and stops after confirmed charging still do.

Frontend checks use simulated entities and actions. They cover atomic saves, entity scoping, rejected requests, retained drafts, feedback, forecasts, missing metrics, completion times, escaping, unrelated-state render suppression and responsive layouts down to 320px. Desktop dark and mobile light previews are inspected locally.

CI validates before release. The archive contains runtime assets and public documentation, excluding development environments, caches, tests and private configuration.

These checks do not prove physical charging, production frontend behaviour or model accuracy for a particular vehicle. Capacity, voltage, efficiency and margin remain assumptions. Production CPU and Recorder storage have not been benchmarked.
