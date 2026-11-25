# Myron runtime-gap follow-up — 2026-11-25

Subsequent charging-level boundary fixes and the decision on how much Xiaomi
thermal compatibility is actually required are recorded in
[the thermal policy review](thermal-policy-review-20261125.md).

This is a source checkpoint, not a request to compile or flash. The user has
confirmed that the booting UFS-fixed 6.12.118 still displays wireless charging
while battery charge falls. No subsequent device result is available.
Libperfmgr remains explicitly deferred. Shared EvolutionX/Lineage build rules,
GKI/KMI compatibility, charging limits and thermal thresholds are unchanged.

## Corrected in this checkpoint

- **Battery properties:** a missing `micharge` client returns a negative vote,
  which the old truth-value check treated as a request to suspend charging.
  Only a positive vote now selects that status. Fuel-gauge properties no longer
  depend on both USB and wireless power supplies existing. Input status accepts
  a successfully observed online supply, preserves errors when neither is
  confirmed online, and reports offline only when both are known offline.
  USB-specific properties still require USB. This corrects reporting; it does
  not itself increase charging current or establish the cause of power loss.
- **Connector protection:** resolve both configured thermal zones before GPIO
  acquisition/output changes; defer while HWID or a zone is unavailable.
  Preserve other errors. GPIO setup frees only resources it successfully
  acquired, and software-only protection no longer fails for having no GPIO.
  This does not create a missing sensor or change a protection threshold.
  General notifier/log callback removal lifetime is outside this correction.
- **CNSS suspend rollback (companion modules repository):** after host-driver
  suspend succeeds, a failed `pci_save_state()` in the disable-PC/RC-control
  branch now resumes the host driver before returning the failure. Other
  suspend vetoes and error values remain intact. This does not establish why
  the earlier device capture returned `-11`.
- **Connector DT checks (companion Android device repository):** before final
  images are emitted, validate both connector zones against their resolved ADC
  phandle, channel number, enabled ancestor buses and thermal-monitor channel.
  Reject missing/disabled/ambiguous bindings; do not rely on numeric phandle
  values. All eight archived merged phone DTBs pass this check. These are old
  captured trees, not newly built or flashed artifacts.

## Verification boundaries

Production-function host harnesses pass 64 battery, 10 antiburn and 14 CNSS
cases with UBSan. Each corresponding pre-change source fails its negative
control. Three modified objects compile for ARM64 using Clang 19.1.7, native
Myron configuration, CFI and MODVERSIONS. Kernel C checkpatch reports no errors
or warnings. Device DT suite passes 21 tests, with two unavailable full-build /
external-DT-tool tests skipped. The new thermal tests cover disabled/missing
ancestors, changed phandles, wrong channels, duplicate handles/channels and
wrong ADC/TM properties. See `runtime-gap-validation-20261125.json`.

No complete new Image, external-module modpost, production Android-toolchain
build, final partition image verification or hardware thermal/charging result
is claimed. Previous wireless queue/session corrections at kernel commit
`238cabb9740f19d3f2495af26f2ec0f6dd4e69b6` remain included.

## Thermal interface blocker identified

The ROM has an import/start configuration for `mi_thermald`; this is static
integration evidence, not proof that the daemon ran on the phone. The vendor
binary references `/sys/class/thermal/thermal_message/*`. No implementation of
`mi_thermal_interface` / `thermal_message` was found in tracked kernel or
modules C/header/Kconfig/Makefile sources. `mi_thermal_interface.ko` is in the
historical excluded-stock-module inventory. Restoring five QTI cooling/alarm
modules does not implement this Xiaomi interface.

Reviewed reference:
[LOS SM8550 mi_thermal_interface.c at 86c2c5c4787b](https://github.com/LineageOS/android_kernel_xiaomi_sm8550/blob/86c2c5c4787bf13b560e587175d10f3968922db3/drivers/thermal/mi_thermal_interface.c).
It implements CPU frequency QoS, panel notifications and Xiaomi sysfs controls.
The current vendor binary additionally contains paths for `atc_enable`,
`charger_only_index`, `display_therm_temp`, `dynamic_tj`, `ipa_cdev_limits`,
`ipa_dump_info`, `ipa_virtual_sensor`, `special_cpu_limit` and `temp_aware` that
are absent from that reference. String presence alone does not prove all nine
are exercised on Myron; matching runtime/configuration evidence is needed.
The older source also uses private class traversal and has unchecked lifetime /
error paths. It is not a drop-in, qualified 6.12 implementation. No empty sysfs
stubs, hardcoded sensor values or unverified replacement thermal policy were
introduced to make these paths appear to work.

The reviewed [MiCode Dada thermal_config.c](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/afb5a488a44e7e980b2ef7b4c145703cfcb7aac5/drivers/thermal/qcom/thermal_config.c)
is a thermal-zone debugfs configuration driver. Its absence alone is not a
missing production thermal-policy implementation, and it is not a substitute
for `mi_thermal_interface`.

## Consolidated checklist disposition

| Item | Current evidence / remaining work |
| --- | --- |
| Wireless parameters / receiver commands / RX queue / CONNECT ordering | Existing source fixes retained and host-checked. New device power gain is unverified; actual charging remains open. |
| Battery provider dependencies / negative client vote | Corrected here; hardware error counts and charging status need later confirmation. Unsupported properties still return errors. |
| QTI CPU/GPU/userspace cooling, dynamic trip, PMIC alarm | Source and load-list fixes retained. Final module loading, cooling policy IDs and SCMI responses need verification. |
| Connector thermal routes / antiburn | Eight archived DT variants pass mapping checks; probe/GPIO correction compiled. New runtime binding and protection behavior unverified. |
| Xiaomi thermal_message / mi_thermald contract | Real source/integration gap identified above; not complete and not papered over with SM8550 stubs. |
| thermal_config | Reviewed source is debug support; not classified as mandatory missing policy. |
| IPA readiness / callbacks / queue ownership | Previously corrected in modules 1500b5df54325748574deb953a87f198cf23d7b5; no new firmware/performance measurement. |
| CNSS suspend | Rollback defect corrected here. Cause of captured -11 remains unknown; vetoes preserved. |
| OCP / SPSS supplier dependencies | OCP built-in, SPSS selected and prior integration retained. Binding/sync_state need current-device evidence. |
| Qualcomm LPM versus generic PSCI | Generic PSCI retained; vendor governor not enabled without matched DT/firmware evidence. Pending-node removal is not proof of equivalent low-power operation. |
| GLINK 32778 / qti_glink_adc / pmic_ecid / MCA platform | Missing module names do not establish the failed property's provider. No competing generic battery client enabled; ownership/provider failures need current logs. |
| PMIC/RPMh resources / SCMI timeout | Need effective DT/command-db/firmware evidence; no fabricated resource or suppressed timeout. |
| charger_partition -95 | Prior unsupported-format repeat suppression retained; writes remain disabled without verified layout. |
| Audio LPI / core vote prints | Print counts alone are not a functional defect; no arbitrary audio change. |
| RNG | ARM SMCCC TRNG and other RNG config present; absent qcom_rng alone is not proof of failed entropy. Runtime CRNG remains unverified. |
| CWB / VPP-CDSP / userspace performance policy | No new device evidence or policy change in this checkpoint. |
| libperfmgr | Explicitly deferred by the owner; no integration changes. |

Do not label this list fully fixed. The source checkpoint preserves the booting
UFS correction and normal `yuzuli` release-label behavior. Complete thermal
interface qualification and measured net wireless charging are still required.
