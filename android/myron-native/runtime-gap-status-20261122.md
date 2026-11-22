# Myron runtime gap follow-up, 2026-11-22

This source update follows review of a device running 6.12.97 #10. It does
not establish runtime results for 6.12.118. The Android device repositories
and libperfmgr migration are deferred until the owner's local device trees
are exported. No EvolutionX shared build source is changed.

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
