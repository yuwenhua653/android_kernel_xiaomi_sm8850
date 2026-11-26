# Myron: official Songyuan reference follow-up, 2026-11-26

## Source baseline and applicability

Kernel parent: `6cece84fc4cc489a7c29bcaa0282e994755457e9`.
Companion modules: `5638362f5eeb3cc0c8bbcd7d9cbf456e0fd9cc74`.
Companion DT: `fb892731a9b9df5ecd076409536d172e564b6850`.

Reviewed official sources:

- [MiCode kernel, da9af1b6d83e](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/tree/da9af1b6d83e1f53e4b8e4f4421e3c4161d2133d): Songyuan inherits Canoe. Its MCA directory is a symlink to an external vendor tree, not a complete MCA implementation. Neither that symlink nor the config selection establishes a wireless charging fix.
- [MiCode Myron charging DT, 396596c6d1ec](https://github.com/MiCode/kernel_devicetree/blob/396596c6d1ec3c349402c50913f781efbf343d9c/qcom/myron-charger-common.dtsi): useful same-board reference, but this revision uses nine-column wireless temperature rows. Our current parser and paired DT use eleven columns, including normal/FFC float-voltage limits. No automatic conversion, borrowed cell limits or FOD replacement was made.
- [MiCode dynamic thermal trip](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/da9af1b6d83e1f53e4b8e4f4421e3c4161d2133d/drivers/thermal/qcom/qti_dynamic_hw_trip.c): initializes from `qcom,trip-temperature` and writes the configured threshold to firmware. Its Canoe thermal DT equals our current file after stripping trailing whitespace; both contain the existing 95000 mC thresholds.
- [MiCode WLAN, 1c7d7a015b4a](https://github.com/MiCode/vendor_qcom_opensource_wlan/blob/1c7d7a015b4a683d50c400847d7f25b72cca4f34/qcacld-3.0/core/hdd/src/wlan_hdd_cfg80211.c): still gates the three-argument monitor-channel callback at 6.13. It does not replace our 6.12.118 backport compatibility.

## Changes

### Dynamic thermal initialization

Use a present DT threshold as the initial value, following the official Canoe contract. Send it through SCMI and publish the zone only after a successful response. An invalid property or failed write remains an error; it is not turned into a successful probe. When the property is absent, retain the firmware-read initialization path. Record the requested value and time only after success. No DT threshold was changed.

This removes the unconditional dependency on a firmware GET operation for boards already supplying the initialization value. It does not establish that the phone's firmware currently rejects GET, nor does it turn an unsupported runtime GET into a fabricated temperature.

### Wireless table parsing

- Check the newly allocated stage pointer, not the existing voltage pointer. Fail on allocation/read errors and require exactly two stage entries per voltage row.
- Build voltage and temperature tables privately and publish them only after complete parsing. Free all allocations from a failed temperature parse, including its child voltage/stage arrays. A failed replacement leaves the previous table untouched.
- Balance the optional cycle-count DT node reference.
- Reject negative battery roles and invalid modes before indexing arrays. Map nonzero supported battery modes to the base/flip property without indexing a two-entry string array with series mode 2. Check the master table for the requested mode, and do not mask an initial normal-table failure with a later base/flip success.
- Retain the eleven-column ABI. The committed test fixture contains unchanged values from the paired Myron DT, including ATL, Coslight and global profiles; it is not a shipping DT replacement.

This patch does not claim to finish successful runtime table replacement/retirement concurrency, all probe-unwind ownership or strategy unregister lifetime. The new parser tests cover failed replacement ownership; they do not establish those broader properties.

### Charging status and forced-full reporting

A wireless FFC termination-current query with no selected voltage profile now returns `-ENODATA` instead of dereferencing a missing table or providing a synthetic termination current. The single-gauge forced-full path checks online, quick-charge state and termination-current query results. Invalid limit samples cannot contribute to the six-sample forced-full counter; failed queries reset that counter. Existing valid-sample multipliers and charging limits are retained.

## Validation at source review

- 26 host suites pass. Three new suites execute production functions: 534 wireless table parsing/ownership cases using all three paired Myron profiles, 9 DT/SCMI initialization cases, and 21 wireless-status/forced-full cases.
- Allocation failures and every table-read failure are injected; the caller's previously published table remains owned and intact. Nine-column input is rejected, not silently reinterpreted. Short and long stage arrays fail.
- Three deliberate regressions fail runtime assertions: checking the wrong allocation pointer, ignoring the SCMI initialization write error, and ignoring the initial online-status error.
- All three modified translation units compile for ARM64 with Clang 19.1.7, CFI, MODVERSIONS and GENDWARFKSYMS. Qualification uses LTO_NONE and disables Rust/BTF in the output config, matching the preceding qualification; shipping fragments are unchanged.
- Driver checkpatch: zero errors and warnings. Full-image/module qualification, if completed, is recorded below and in the companion JSON.

## Remaining device evidence

Wireless net charge gain remains unverified. Actual QTI cooling/thermal HAL behavior, mi_thermald private interfaces, firmware SCMI responses, live deferred probes and Wi-Fi suspend behavior still require the paired build on the phone. Generic PSCI remains selected; no vendor LPM governor or libperfmgr was substituted. The UFS boot correction and `yuzuli` release label are retained. This batch changes only the kernel repository; shared EvolutionX, device policy and companion module/DT repositories are not rewritten.
