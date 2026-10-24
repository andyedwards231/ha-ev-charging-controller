# Verification

Release validation uses Home Assistant 2026.10.0, Python 3.14, memory-only storage replacements and mocked charging services. It is designed to run without connecting to production Home Assistant or operating a vehicle.

The Python suite covers planning, partial and invalid rates, gaps, overlaps, clock changes, current-amp changes, learned power, forecasts and caching. Controller coverage includes monitoring, tariff handover, boost, overrides, completion latches, retries, config flows and lifecycle cleanup. Frontend registration is exercised without Lovelace writes.

Command-dispatch regressions check that malformed rates stop controller-owned target charging and that a completed deadline request stays stopped after the battery level falls. The immediate input recheck uses the same control rules as the published decision; invalid planner data does not grant command authority over an unowned charge.

Start-feedback scenarios model Tessie's optimistic switch update followed by an old cloud report, then real charging confirmation. The transient off report must not create a manual hold; explicit Home Assistant user stops and stops after confirmed charging still do.

Frontend tests use simulated entities and actions. Their coverage includes atomic saves, entry scoping, rejected requests, retained drafts, feedback, forecasts, missing metrics, completion times, escaping, unrelated-state render suppression and responsive layouts. These checks exercise frontend code in a test harness; they do not establish behaviour in a live Home Assistant browser session.

CI is configured to run Python and frontend tests, Hassfest and HACS validation before a release archive is built. The archive contains runtime assets and public documentation, excluding development environments, caches, tests and private configuration.

Automated checks do not prove physical charging or model accuracy for a particular vehicle. Capacity, voltage, efficiency and margin remain assumptions. Production CPU and Recorder storage have not been benchmarked.
