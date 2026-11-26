# Charging transport and recovery follow-up — 2026-11-26

This source update closes additional reproducible failure paths; it does not
establish net wireless battery charging or complete device thermal qualification.
The last supplied hardware result remains: charging is displayed but battery
charge falls. No newer device result was available during this update.

## Corrections

- MCA GLINK now keeps the provider alive across queued property requests and
  response copies with SRCU. Removal withdraws admission, aborts an outstanding
  request, drains API users, unregisters the callback-draining transport client,
  and cancels queued synchronization work before managed memory is released.
- GLINK subscriber lists now use SRCU, reject duplicate registrations and offer
  draining unregister APIs. State delivery is serialized: an old queued UP
  cannot follow an already delivered DOWN. Provider rebind queues synchronization
  for existing consumers after publication. The 0x8009 QBG owner is not enabled
  as a new transport client; its firmware contract remains unqualified.
- The sub-PMIC proxy now unwinds previously registered BC1.2/QC/buck providers
  on later probe failure. Remove drains GLINK, provider and reboot callbacks,
  cancels work, frees pending notifications and releases its wakeup source.
  Missing HWID causes deferred probing, not an allocation error.
- QC provider dispatch now uses SRCU with an atomic ops/data publication and a
  matching unregister API, so replacement/removal waits for in-flight callbacks.
  Existing public callback signatures and structure layout are preserved.
- Sub-PMIC configuration synchronization uses a per-device bounded retry budget.
  A new GLINK-UP generation and successful synchronization reset the budget.
  An older in-flight generation cannot consume the new generation's retries.
  Existing retry timing, property payloads and regional configuration are retained.
- Wireless input-current ramps stop on a failed command or an observed disconnect,
  clamp both directions to the target and reject invalid arithmetic parameters.
  BPP adapter and EPP recharge callers no longer bypass a failed ramp by issuing
  its final high-current command or recording success. Existing target currents
  and protection thresholds are unchanged.
- The Bixi-only half-bridge path now requires successful commands and fresh,
  nonnegative current/positive voltage samples before switching. This branch is
  not claimed as a fix for Myron charging. Drawload polling no longer interprets
  a failed status read as FULLON/TAPER; its original timeout policy is retained.

## Validation

- All 23 committed host suites pass, including existing thermal, wireless, UFS
  power-balance and release-label tests.
- New suites execute production functions: 104 wireless ramp/bridge/status cases;
  131 QC registration/lifetime cases; 67 GLINK request/registry/rebind cases;
  27 sub-PMIC recovery/probe-unwind cases with 60 retries per failed cycle.
  Threaded tests block callbacks across replacement/removal. Host backends model
  lifetime primitives; they do not replace kernel lockdep/KCSAN or device testing.
- Four deliberate regressions are rejected by runtime assertions: ignoring a
  failed ramp command, stale UP delivery, failure to reset the retry budget and
  unregistering QC without draining the active callback.
- All four modified driver translation units compile for ARM64 with Clang 19.1.7,
  the native GKI/Canoe/Myron fragments, CFI, MODVERSIONS and GENDWARFKSYMS. Local
  qualification uses LTO_NONE and disables Rust/BTF, as before. Production config
  fragments are unchanged. Detailed hashes/results are in the companion JSON.
- Driver patch checkpatch: zero errors and warnings. No new complete Image,
  full module modpost, Android production build or final image check is claimed.
  The preceding 427-module qualification applies to its recorded earlier source.

## Remaining checklist and boundaries

| Item | What still requires evidence |
| --- | --- |
| Wireless net charging | Rebuild the paired kernel/modules and measure real charge/energy gain. These fixes are not a new phone result. |
| Thermal | Keep mi_thermald and existing limits. The board-temperature bridge and cooling fixes remain; actual QTI HAL sensor mapping, policy ownership and cooling response need the running ROM. |
| OCP/SPSS, GLINK properties | Confirm live provider binding, deferred probes, sync_state and property failures after the update. |
| Wi-Fi / IPA | Earlier source fixes are retained. Firmware behavior and the recorded CNSS -11 suspend veto still have no established cause. |
| Qualcomm LPM | Generic PSCI is retained. A vendor governor is not substituted without matching DT/firmware and measured idle residency. |
| PMIC command-db / SCMI | No missing resource is fabricated and no timeout is suppressed; effective firmware/DT evidence is required. |
| charger_partition | Layout is unverified, so writes remain disabled. |
| Audio / RNG | Log frequency or an absent module name alone does not prove malfunction. Runtime audio, CRNG and firmware behavior remain separate checks. |
| libperfmgr | Deferred by the owner. |

The checked device-common source still selects QTI thermal HAL and imports
mi_thermald. It does not provide a board-specific HAL sensor mapping in this
checkout. The older reported sys-therm-0 mismatch is not enough to invent a
replacement sensor or alter the running ROM's policy.

`capture-runtime-gaps.sh` collects charging trends, thermal zones/cooling states,
HAL snapshots, running FDT when readable, deferred probes and kernel logs. It
only reads system interfaces and writes a local evidence archive. It was syntax
checked, not run on a phone. Root shell access improves coverage; lack of access
is recorded. Polling wakes the device, so this is not an overnight-power test.

Only this kernel repository is changed. Companion modules/DT revisions remain
5638362f5eeb3cc0c8bbcd7d9cbf456e0fd9cc74 and
fb892731a9b9df5ecd076409536d172e564b6850. No shared EvolutionX, device/vendor policy,
libperfmgr, UFS boot fix, release naming or thermal/charging limit was changed.
