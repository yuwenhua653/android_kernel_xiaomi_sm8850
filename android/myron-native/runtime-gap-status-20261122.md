# Myron runtime gap follow-up, 2026-11-22

This source update follows review of a device running 6.12.97 #10. It does
not establish runtime results for 6.12.118. The Android device repositories
and libperfmgr migration are deferred until the owner's local device trees
are exported. No EvolutionX shared build source is changed.

## Consolidated follow-up: IPA event lifetime and CPU cooling registration

Paired modules commit: `1500b5df54325748574deb953a87f198cf23d7b5`.

This batch keeps the previously submitted wireless charging and kernel DT
changes intact. Android device trees, shared EvolutionX build sources and
libperfmgr remain outside this batch. Earlier follow-up sections below record
historical revisions; their open source issues are superseded where addressed
here. Runtime validation is still a separate requirement.

Implemented together:

- Replace the uC-ready callback's inspection of an internal work-list entry
  with explicit publication under a spinlock and a dedicated, allocation-free
  work item. Retain early notifications until synchronous pipe/queue setup is
  complete; repeated notifications cannot mark an unconfigured pipe ready.
  Actual setup completion, not notification receipt, controls idempotence.
  Recovery and teardown still prevent new setup work.
- Serialize the IPA provider's ready callback registration, delivery and
  removal. WDI instance cleanup removes only its matching callback and waits
  for an executing atomic callback before the owning context is released.
  A second pending owner gets EBUSY instead of silently replacing the first.
  Callbacks must remain atomic and must not register/unregister themselves;
  the paired WLAN callback only records readiness and schedules work.
- Track successful WDI initialization so setup-error cleanup releases a live
  registration exactly once. Validate a cleanup handle/context before logging
  through it, and reset the cleaned instance's endpoints rather than instance 0.
- Dispatch queued packet/filter-delete messages synchronously from stack
  storage. This removes the secondary allocation that could lose a filter
  completion or strand packets. Firmware-owned allocations retain a freeing
  wrapper; the dispatcher does not retain the borrowed message pointer.
- Allocate the entire filter-reservation notification/SMMU pair before
  publishing either member. Allocation failure, duplicate pending messages
  and a closed queue free only locally owned messages. Previously failure
  could free the SMMU message twice, or free it after publication to work.
- Protect ordinary message slots and producer publication against duplicate
  callbacks and queue teardown. Ready setup stops first, but ordinary control
  responses remain enabled while pipe shutdown waits for filter acknowledgements.
  Only then is ordinary publication closed and its work/packet queues drained.
- Reject out-of-range vdev IDs before indexing the IPA interface map.
- Make CPU cooling registration work idempotent. Repeated CPU-online events
  may requeue an executing work item; the next invocation now retains the
  registered cooling device, frequency table, policy reference and QoS request.
  The hotplug callback no longer reads the worker-owned cdev pointer.

Regression coverage: 2,959 production IPA initializer/queue cases, 4,353
ready-publication ordering cases (including 256 concurrent publish/notify
pairs and recovery gating), 519 provider callback/instance cases, 304 message
ownership/vdev-bound cases, and 102 CPU registration/retry cases. These 8,237
cases use UBSan. The readiness harness models the work executor and does not
simulate firmware or the complete hardware pipe setup. The old CPU worker
reproduces duplicate QoS ownership; old IPA reservation code reproduces both
pending-message replacement/leak and double-free on allocation failure.
Existing IPA vote-readiness and CPU/GPU QoS regression checks also pass.

Build qualification for this batch: `Image modules` completed successfully
for the native Myron configuration, including in-tree modpost and all
353 modules from `modules.order`. CFI and MODVERSIONS were enabled; this host
Clang 19.1.7 qualification does not enable Rust/BTF. Both complete external
`qca_cld3_peach_v2.o` and `ipam.o` compiled and linked for ARM64. The new
matching-owner callback removal symbol resolves inside `ipam.o`. A final
incremental WLAN check confirmed the final sources are up to date.

See [the validation record](runtime-gap-validation-20261122.json) for source
and artifact hashes. The host kernel was built from the recorded parent plus
the driver change, so its local release suffix contains `dirty`; this is not
a distributed flashable image. The complete external-module modpost, Android
Clang/Rust/BTF build, final images and runtime behavior remain unverified.

### Current disposition of the original runtime checklist

| Gap | Source/integration disposition |
| --- | --- |
| Wireless RX and power-supply reporting | Existing submitted fixes retained; await compiling/flashing 6.12.118 and measuring actual battery input. |
| IPA premature votes and callback/queue lifetime | Source corrections and host tests completed in the paired modules; firmware readiness and power impact still require device results. |
| CNSS suspend -11 / host -16 | Existing diagnostic branches retained; old log does not establish which WoW/host veto caused it. Do not bypass suspend vetoes or invent firmware acknowledgements. |
| QTI CPU/GPU/userspace/dynamic-trip cooling and PMIC temperature alarm | Sources/builds restored; duplicate CPU registration fixed here. Android load lists and vendor sensor/cooling policy matching remain deferred. |
| conn_therm and skin mapping | Requires effective DT/thermal-HAL policy; not repaired by adding another arbitrary sensor name in the kernel. |
| Generic PSCI versus Qualcomm LPM | Optional vendor sources retained, default remains generic PSCI. Vendor governor needs paired DT/load order/userspace enablement; no speculative switch. |
| OCP/SPSS and other supplier reports | OCP is built in and SPSS is selected as a module in qualification config. Actual module loading and supplier binding need final-image/device evidence. |
| GLINK owner 32778 and MCA property errors | Do not enable a competing QTI battery supply to silence owner messages. Missing provider values preserve errors; expected ENODATA handling was corrected earlier. |
| PMIC/RPMh missing resources and SCMI -110 | Effective board DT, command-db/firmware protocol evidence required. No fabricated resources or suppressed timeout. |
| Charger partition -95 | Repeated unsupported-format probing already stopped. Storage writes remain disabled pending a verified layout. |
| Audio LPI prints | Reviewed unconditional debug output is not proof of pinctrl failure; no new audio workaround. |
| RNG module absent | Does not establish CRNG failure. No security/entropy claim inferred from module absence. |
| CWB off-screen polling, VPP/CDSP session, Perf HAL nodes | Userspace/vendor integration work; libperfmgr explicitly deferred with device repositories. |

No remaining row is claimed fixed on hardware from the 6.12.97 capture.
Additional firmware filter-result/slot semantics and global-context lifetime
outside the gated event producers are not qualified by these tests.

## Follow-up: IPA reinjection packet ownership

Companion modules commit `f705cc47d21465eb323ee8eae7be593eb07b29cb`
fixes two source-confirmed leaks, without extending the wireless charging
changes already awaiting compilation/device qualification:

- A dequeued reinjection packet was leaked when allocation of its dispatch
  message failed. Free that packet and continue draining the queue, so a
  transient allocation failure does not strand the remaining queued packets.
- Cancelling pending work does not consume its ring. During existing queue
  teardown, drain reinjection packet ownership before freeing the entries.
  Filter-delete notifications carry handles, not owned packet buffers, and
  are not treated as packets.

The expanded production-function harness `test_ipa_init_cleanup.py` passes
2,703 cases under UBSan, covering every ring position and occupancy, wrap,
single/persistent message allocation failures, cancelled work, and the prior
initializer/unwind checks. The preceding source fails packet ownership
assertions; applying only the worker fix still reproduces the teardown leak.
The existing IPA performance-readiness regression also passes. The changed
`wlan_ipa_core.o` compiled for ARM64 with the native Myron configuration and
host Clang 19.1.7. This is not a new complete external-module modpost or ROM
build, and no suspend/power improvement has been measured.

Scope limits: this preserves the existing producer shutdown contract; it
does not establish that all producer-versus-teardown races are resolved.
UC-ready callback publication/duplicate-event ordering, the missing ready
notification in the old capture, and the CNSS suspend handshake still need
qualification. Filter-delete notification allocation failure handling is
also unchanged. No Android device repository, libperfmgr policy or DT was
changed in this follow-up.

## Follow-up: RX state and IPA lifecycle (no device-tree dependency)

The SC96281 register declaration defines `t_die` as signed 16-bit. Its
reader and Celsius conversion now preserve that sign; negative values no
longer become extremely high positive temperatures. Failed reads return
before logging an output that was not populated. The existing integer
Celsius API and thermal limits are unchanged.

Additional RX state corrections:

- Cache a transmitter fan-speed command only after successful transmission,
  with its comparison/update under the transfer mutex. A failed request for
  the same speed can be retried rather than silently skipped.
- Cache the complete zero-padded transparent packet actually written to RX.
  A shorter packet no longer retains bytes from the previous longer packet;
  failed writes preserve the previous successful packet.
- Stop factory current/voltage replies on sample-read failure instead of
  serializing an uninitialized measurement and hiding the read error.

IPA lifecycle corrections:

- Allocate both control-message queues before initializing their work items.
  Fail with `QDF_STATUS_E_NOMEM` at either allocation stage instead of
  registering callbacks with missing queues. Partial unwind frees only
  prepared queues and cancels only initialized work; freed pointers are
  cleared and a subsequent initialization can allocate fresh queues.
- On synchronous TX-buffer SMMU mapping failure, disconnect already connected
  IPA pipes and tear down STA system pipes, matching the existing asynchronous
  UC-ready failure path.
- After draining UC work on normal teardown, clear `uc_load_handled` before
  disconnecting the pipes. Subsequent vote calls no longer see stale readiness.
  Teardown also clears freed queue pointers. This does not serialize an
  already in-flight vote or establish that all UC-ready/SSR races are solved.

Validation for this follow-up: host production-function tests cover all
65,536 raw temperature values and 11 state/error cases, plus 15 IPA lifecycle
scenarios (four allocation sites, retry, setup/mapping failures and normal
teardown). Both harnesses reproduce a defect on the preceding source and pass
with these changes under UBSan. Existing 32 command, 13 authentication, 4,363
IRQ cases and the IPA vote-readiness regression also pass. Changed
`sc96281_core.o` and `wlan_ipa_core.o` compile for ARM64 with native Myron
configuration and host Clang 19.1.7. No new full image/external-modpost or device
result is claimed. Actual charging power, missing UC-ready notifications and
the captured CNSS suspend failure remain open.

New harnesses: `tests/test_sc96281_state.py --kernel-root <kernel>` in this
directory and `android/myron-native/tests/test_ipa_init_cleanup.py --modules-root
<modules>` in the companion repository, both run with `python3`.

## Follow-up: wireless command and authentication error paths

Further source review found independently reproducible failure-path defects:

- Eight SC96281 parameter/packet writers issued the command trigger even
  after the payload write failed. A successful trigger then replaced the
  original I2C error with success. They now stop at the failed payload write
  and preserve the error. The voltage cache updates only after both stages
  succeed. Failed CEP reads also abort the voltage change.
- The direct adapter read now returns an I2C failure without publishing a
  cached adapter as a fresh reading. Authentication reads stage the required
  adapter/UUID fields before publishing their cache, returning the first
  read failure. The wireless strategy checks authentication, UUID and adapter
  read errors before proceeding with that authentication event.
- Repeated authentication events replace the assembled transmitter UUID;
  previously `|=` retained bits from a previous value. The top-byte shift
  explicitly uses an unsigned 32-bit value.

These are error-handling corrections to the existing Xiaomi MCA/SC96281
implementation. No authentication requirement, FOD parameter, voltage/current
limit or thermal limit is relaxed. They do not prove that the observed
non-charging event took one of these paths, or establish negotiated input
power. The existing firmware/strategy recovery behavior is retained; this
change adds no automatic authentication retry.

WLAN follow-up exposes the two previously debug-only system-suspend rejection
messages for pending RX frames and endpoint work at info level. The captured
`-16`/`-11` failure alone cannot distinguish these branches. No suspend veto,
return value or WoW timing was changed; this is diagnostic coverage, not a
claim that CNSS suspend is fixed.

Follow-up validation: both new regression harnesses reproduce failures on the
preceding source. The corrected source passes 32 command/CEP/cache cases and
13 authentication/cache/event/UUID cases (the latter with UBSan), plus the
existing 4,363 IRQ cases. `sc96281_core.o`, `mca_basic_wireless.o` and
`wlan_hdd_driver_ops.o` compile for ARM64 with host Clang 19.1.7 and the native
Myron configuration. This follow-up is object-level qualification; the full
Image/modpost result below belongs to the preceding update, not this revision.

Run the new harnesses as `python3 android/myron-native/tests/test_sc96281_commands.py
--kernel-root <kernel>` and `python3 android/myron-native/tests/test_sc96281_auth.py
--kernel-root <kernel>` (each command on one line).

## Implemented source corrections

- The MCA wireless power_supply now reports RX voltage/current/temperature
  through the wireless platform provider, in uV/uA/tenths of Celsius.
  Previously it reported fuel-gauge voltage/current (including mV as uV),
  omitted TEMP, and returned success without a value for several properties.
  Unavailable providers and unsupported limits return ENODATA without
  publishing a stale or invented sample. These telemetry changes do not
  establish that negotiated wireless input power is adequate.
- Optional battery/USB ENODATA results no longer produce error-level spam.
  Other provider errors remain visible. Missing property implementations
  are not represented as completed merely because expected errors are quiet.
- Successfully parsed wireless voltage/temperature rows use debug logging;
  actual parse failures still use error logging.
- Charger storage with an unspecified, immutable header-version parameter
  no longer scans/wakes UFS 21 times. Storage remains unavailable and writes
  remain gated; neither the partition format nor a safe write policy is guessed.
- The companion modules update prevents periodic WLAN IPA performance votes
  before uC pipe setup has registered its PM client. The synchronous setup
  path now records completion too. Bandwidth-based voting uses the same
  completed-setup condition. Actual IPA failures include handle and bandwidth.
  This prevents premature requests; it does not fix an absent firmware-ready
  notification or certify working offload/suspend.

## Thermal drivers and provenance

The following missing implementation files are imported from
LineageOS/android_kernel_qcom_sm8850 at
`557159b6a0d06f1c6f07ec4c1f22bc9309a113e4`, retaining their licenses:

- drivers/thermal/qcom/qti_cpufreq_cdev.c
- drivers/thermal/qcom/qti_devfreq_cdev.c
- drivers/thermal/qcom/qti_dynamic_hw_trip.c
- drivers/thermal/qcom/qti_userspace_cdev.c
- drivers/cpuidle/governors/{qcom-lpm.c,qcom-lpm.h,qcom-cluster-lpm.c,
  qcom-lpm-sysfs.c,trace-cluster-lpm.h,trace-qcom-lpm.h}

Thermal adaptation checks frequency-table entries/order, QoS registration
errors, GPU supplier/OPP readiness, SCMI read failures, cooling-device
registration errors, DT references, and cancellation of pending CPU work
before removal. OF module aliases are provided. Native Makefiles build the
four thermal drivers and the existing PMIC temperature alarm as modules.

**Runtime integration is still pending:** the Android device load lists must
include the required modules and final images must contain them. An additional
compiled module is not proof that Android loads it. Verify cpu-cluster0,
cpu-cluster1, gpu, display-fps, PMIC thermal zones and cpu-hw-trip-* against
the actual vendor policy, including cooling-state effects and recovery.
Existing generic CPU/GPU cooling stays intact. No thermal threshold is raised.
`thermal_config` is a debug interface and remains disabled.

## LPM is available for qualification, not switched on

The Qualcomm LPM source and native build rule are restored, but the ordinary
Myron fragment still disables it and the matching DT remains generic-PSCI-v2.
Upstream initializes `sleep_disabled=true`; the vendor userspace normally
changes this. The governor also depends on WALT interfaces when WALT is a
module. Enabling it or its auxiliary cluster nodes without the paired load
order and initialization would risk regressing deep sleep and fw_devlink.

The qualification build explicitly enables CPU_IDLE_GOV_QCOM_LPM=m only in
its output .config. This is not a shipped default. Restore cluster-device0/1/2
only with the corresponding device integration, then compare PSCI/domain
residency and suspend statistics; disappearance of pending messages alone
does not qualify the vendor policy.

## Remaining checklist

| Item | State / next evidence |
| --- | --- |
| libperfmgr and Perf HAL node mismatches | Deferred by owner; needs actual Android device tree and runtime node inventory. |
| skin reporting and mi_thermald policy | HAL runs, but skin is absent from captured output; verify installed HAL/SKU and sensor mapping. |
| Wireless effective charging | Retain prior RX IRQ fix; verify final DT and RX/input/battery measurements on the same device/charger. |
| GLINK owner 32778 | QTI battery client; generic battery-charger node is disabled while MCA is enabled. Do not enable duplicate battery/USB supplies just to consume a message. Firmware/client routing remains to be qualified. |
| CNSS suspend | One explicit driver failure in this capture, not all four failures. WoW handshake and firmware readiness remain open. |
| CWB/RGB off-screen retry | Userspace sampling lifecycle needs device/vendor source; no kernel workaround added. |
| VPP/CDSP session crash | Needs matching userspace DSP clients/startup review; CDSP boot success alone is insufficient. |
| PMIC/RPMh resources | Compare effective board DT and stock command-db; do not delete suppliers on error alone. |
| SCMI telemetry | Firmware protocol/timeout still unverified; new thermal driver preserves error reporting. |
| Charger persistence | Disabled until header/layout is verified; no writes enabled. |
| RNG | Missing qcom_rng is not evidence of a broken CRNG; entropy-source audit remains separate. |
| Audio LPI output | Unconditional error-level debug prints are not proof of a pinctrl failure. |

## Validation

Passed on 2026-11-22 using host LLVM/Clang 19.1.7 targeting ARM64:

- `gki_defconfig vendor/canoe_GKI.config vendor/myron_GKI.config`, followed
  by `make ARCH=arm64 LLVM=1 Image modules`, including full in-tree modpost.
  CFI and MODVERSIONS were enabled. Rust and BTF were not enabled in this
  host qualification environment; this is not the Android production toolchain.
- A separate qualification of the same configuration with
  `CPU_IDLE_GOV_QCOM_LPM=m` also passed `Image modules` and modpost. The
  configuration was restored to the ordinary disabled setting and rebuilt
  successfully before publication. The optional module declares its
  `sched-walt` dependency.
- The four restored thermal modules and `qcom-spmi-temp-alarm.ko` were
  inspected as ARM64 ELF. Dynamic hardware trip declares dependencies on
  `qcom_scmi_client` and `qcom_ipc_logging`.
- Changed WLAN `wlan_ipa_main.o`, `wlan_ipa_core.o`, `wlan_ipa_rm.o`, and
  external IPA `ipa_pm.o` compiled against this kernel. This was an object
  check, not a complete external-module modpost/build.
- Production-function regression harnesses passed for wireless RX units,
  failed providers and unsupported properties; CPU/GPU cooling-state bounds,
  failed/inactive QoS requests and release; and periodic IPA requests before
  connection, after setup, after reset, and with genuine provider errors.
- The existing SC96281 IRQ regression passed 4,363 cases.

Reproduce the added harnesses with `python3` and `--kernel-root` for
`tests/test_wireless_psy.py` / `tests/test_thermal_qos.py`, or
`--modules-root` for the companion repository's
`android/myron-native/tests/test_ipa_perf_ready.py`.

These checks do not substitute for the Android Clang/Rust/BTF build, complete
external module linkage, final image/module load-list checks, or device
testing. No flashable artifact is qualified by this source update.
