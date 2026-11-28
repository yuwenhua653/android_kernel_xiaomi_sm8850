# Myron runtime follow-up, 2026-11-28

Base: b5ed8bcc4a5ada8b27ad28373fb8dbe060a25a2e (Linux 6.12.118).
The device boots and the user reports normal charging. Do not undo the UFS,
wireless table/charging, generic PSCI or module ordering corrections.

## Changes

- CPUSS telemetry: the first SCMI shared-memory query returned ETIMEDOUT at
  boot. Return EPROBE_DEFER for that transport timeout, as the vendor SCMI
  protocol initialization already does, so the driver core can retry later.
  Preserve other errors and report the stage through dev_err_probe. Do not
  map memory or publish a counter provider until the query succeeds. This
  does not prove that firmware will support/respond to a later request.
- QSMMUv500: child registration was printing a fatal-looking error while its
  caller was already deferring the parent probe. Return EPROBE_DEFER explicitly
  and record the reason on the parent through dev_err_probe. This is a
  diagnostic correction; it does not bypass an unready TBU or claim to repair
  a failed hardware probe.

## Validation

`python3 android/myron-native/tests/test_telemetry_probe.py --kernel-root .`
executes the production probe with mocked firmware/mapping backends under host
GCC and UBSan: 12 failure cases and a successful retry pass. Covered cases
include timeout, ordinary transport errors, unsupported protocol, allocation
and each mapping failure, debugfs failure and malformed shared-memory metadata.
Removing timeout deferral deliberately makes the test fail. Checkpatch on both
C changes: zero errors/warnings/checks. No ARM64 production rebuild or hardware
retest of this commit has been performed.

## Companion ROM correction

The device common tree labels vendor.sys.thermal.bcl.boot_completed as an
exact boolean using the existing vendor_thermal_normal_prop type, and grants
the existing performance HAL read-only enumeration of thermal_data_file
folders. The latter matches a separate runtime directory-read denial. Neither
change requires libperfmgr or permission to write thermal configurations.
These SELinux changes require a ROM policy/vendor rebuild, not just boot.img.

## Explicitly still open

- VPP/FastRPC: deferred at the user's request. The current QCOM policy has a
  neverallow against vendor_vppservice reading vendor_qdsp_device. Adding only
  a device allow cannot compile; no relabeling or permissive workaround is used.
- Board temperature: board_sensor_temp still returned ENODATA in the submitted
  run. mi_thermald has a real scalar writer, but its initialization/configuration
  and live writes still need checking. Fixing a boot property is not proof of
  board-temperature publication. No synthetic sample or placeholder dynamic_tj
  control is introduced.
- Wi-Fi: failures coincide with connection/EAPOL activity. Keep the suspend
  guard; these logs do not establish a stuck state requiring a driver change.
- SPMI reads at slave 4/13, register 0x104 fail early. No PMIC nodes have been
  disabled and no WARN suppression is used without board/firmware evidence.
- PMIC GLINK owner 32778 maps to MSG_OWNER_CHG_ULOG in
  drivers/soc/qcom/pmic_pdcharger_ulog.c. It is not evidence that ADC is missing;
  this identification alone is not proof that the full logging transport works.
- BTF mismatch remains a debug/type-information qualification issue. There is
  no Unknown symbol or vermagic rejection in this run. Charger storage remains
  disabled until its on-disk header version is verified.
