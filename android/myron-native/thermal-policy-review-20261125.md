# Myron thermal policy and charging interface review — 2026-11-25

## Decision

**It is not necessary to reproduce the entire Xiaomi thermal stack. It is
necessary to retain a complete, validated thermal-control path.** The current
Myron ROM is not ready to disable `mi_thermald`: its replacement has neither
been implemented nor qualified. Keep the current daemon/configuration while
repairing the interfaces it actually needs. Do not treat every sysfs string in
the binary as an automatically mandatory feature. Libperfmgr remains deferred.

Android's [thermal mitigation requirements](https://source.android.com/docs/core/power/thermal-mitigation)
cover sensor/severity reporting and mitigation behavior; they do not require a
particular manufacturer's daemon. This is an engineering distinction between
the required behavior and the implementation providing it. A Thermal HAL
package alone is not a calibrated device mitigation policy.

| Layer | Required behavior | Current direction |
| --- | --- | --- |
| Hardware / firmware protection | PMIC/SoC critical protection and charger IC safeguards | Preserve vendor-supported protection and limits. |
| Kernel sensors and actuators | ADC/TSENS temperatures; CPU/GPU cooling; charger current votes; connector protection | Repair standard interfaces and existing Xiaomi MCA drivers. No arbitrary sensor aliases or higher limits. |
| Device thermal policy | Skin estimation, hysteresis, CPU/GPU/charging limits, camera/display/modem coordination | Keep existing Xiaomi policy until a complete alternative is validated for Myron. Only required compatibility interfaces need implementing. |
| Android reporting | Accurate AIDL temperatures, severity and cooling status | Verify QTI HAL sensor mapping for the actual ROM source. Generic platform labels are insufficient. |
| Power HAL / libperfmgr | Workload hints and performance requests | Separate task; not a replacement for the thermal policy; still deferred. |

## What SM8550 actually does

Reviewed LOS device tree commit
[`f9a8fe87c9334c6ca2df588aa3f1e7f25f71d8d1`](https://github.com/LineageOS/android_device_xiaomi_sm8550-common/tree/f9a8fe87c9334c6ca2df588aa3f1e7f25f71d8d1):

- `common.mk` selects `android.hardware.power-service.lineage-libperfmgr` **and**
  `android.hardware.thermal-service.qti`.
- `proprietary-files.txt` retains `mi_thermald` and its init file.
- `init/init.sm8550.rc` imports that file and configures Xiaomi thermal sysfs
  attributes. It also retains Xiaomi profile selection.

Thus changing to libperfmgr does not imply removing Xiaomi thermal policy.
These are reference-source facts, not proof of what an arbitrary SM8550 phone
is currently running. The older SM8550 kernel interface reviewed in the prior
checkpoint is also not automatically sufficient for Myron's newer userspace.

## Remaining concrete integration gaps

1. **Board-temperature notification:** four Myron MCA components register for
   `MCA_EVENT_THERMAL_BOARD_TEMP_CHANGE` (buck, fuel gauge, smart charging and
   connector protection). The tracked kernel source has receivers but no
   publisher for that event. The older SM8550 `board_sensor_temp` store does
   not publish this MCA event either. Adding only the old sysfs filenames
   would leave this contract incomplete. Input format, unit, update source and
   lifetime must be established before adding the required bridge; no fake
   temperature or substituted physical sensor has been introduced.
2. **Skin reporting:** the reviewed public QTI thermal HAL
   [`e2ff2bbb4a90503f88d2caa103fb6ed483601043`](https://github.com/LineageOS/android_hardware_qcom_thermal/tree/e2ff2bbb4a90503f88d2caa103fb6ed483601043)
   has a Canoe profile using `sys-therm-0` for SKIN/virtual-temperature inputs.
   That node is absent from all eight archived merged Myron DTBs. The DT
   `thermal-message` instead names `VIRTUAL-SENSOR0`. This is a reference
   mapping mismatch to investigate, not proof that the user's current ROM
   uses this exact HAL commit. A board-specific calibrated mapping is needed;
   renaming `conn_therm` or another sensor to silence lookup errors is not a fix.
3. **Userspace ownership:** Myron imports `init.mi_thermald.rc`; the supplied
   `thermal-engine-v2` init service is commented out. Do not start another
   policy daemon alongside it just because its executable exists. Static
   configuration does not prove either service's live state.

No blanket import of the nine additional proprietary attribute names, no
empty sysfs stubs, no Qualcomm/Xiaomi policy double-start, no shared ROM source
changes, and no libperfmgr integration are part of this update.

## Source fixes completed in this update

The current MCA charger thermal interface had defects regardless of which
userspace thermal implementation controls it:

- Wireless limit handling checked the initial local zero before assigning the
  actual ordinary/super-charge level. Check the selected level before any
  event or table lookup instead.
- The three level sysfs stores accepted negative and oversized values and
  wrote them into shared state before validation. Parse into a temporary,
  validate against the declared and physical table limits, then publish.
  Rejected writes preserve the previous level and votes. Reject malformed and
  overflowing values using standard `kstrtoint` errors.
- Add lower/physical bounds at all four wired/wireless table consumers,
  including the separate zero-based flip arrays. Table data is unchanged.
- The standard cooling device advertised `max_level + 1`, despite the table
  handler rejecting that level, and accepted arbitrary unsigned states before
  narrowing to int. Report the valid maximum and reject invalid requests
  before mutation. The archived Myron tables contain 15 rows: levels 0–15 are
  valid, while the old interface advertised 16. This update changes no valid
  level's configured current or temperature threshold.

This corrects invalid-input and maximum-state behavior. It is not evidence
that the phone actually supplied an invalid level, or that these errors are
the sole cause of the reported wireless power deficit.

## Validation

`tests/test_charger_thermal_levels.py --kernel-root <kernel>` executes extracted
production functions with mocked sysfs, time and voting backends. All 1,385
cases pass under UBSan: each logical table size from 0 to 16, all valid levels,
negative/overflow/malformed input, ordinary/super-charge selection, rejected
write preservation, cooling maxima and unsigned overflow, flip-array bounds,
and unchanged valid table/current-minimum voting. Independent sysfs, cooling
and consumer negative controls all fail on the preceding source.

The modified `mca_charger_thermal.o` compiles for ARM64 with native configuration,
Clang 19.1.7, CFI and MODVERSIONS. This is not a new full Image/modpost/ROM build
or hardware thermal qualification. Existing thermal table bytes, DT data,
UFS boot fix, wireless queue/session corrections and `yuzuli` label remain
unchanged. See `thermal-policy-validation-20261125.json` for hashes.

The checkpoint still does not authorize calling the entire adaptation fixed:
net wireless charge gain, thermal daemon/interface behavior, real cooling
responses and skin severity remain to be verified. No compile/flash request
is made to the owner in this update.
