# Myron wireless follow-up, 2026-11-25

Latest source update: [wireless sample/error handling](wireless-sample-followup.md)
adds validated-current voting, balanced battery references and thermal/FFC
failed-sample protection. Hardware net charging remains unverified.

Subsequent battery/connector/CNSS corrections and the newly identified Xiaomi
thermal-interface gap are recorded in [the consolidated follow-up](runtime-gap-followup-20261125.md).
That checkpoint supersedes the earlier next-test recommendation below; the
current batch is not yet a complete thermal/charging qualification.

The user reports that the booting 6.12.118 build with the UFS ownership fix still
shows wireless charging while battery charge decreases. The previous SC96281
index-to-bitmask fix remains necessary, but was not a complete charging fix.

## Source defects corrected

1. Basic wireless RX interrupts and transparent TX tasks shared `header`,
   `list_lock` and `wait_que`. The two consumers cast nodes to different types:
   `strategy_wireless_irq_node` and `trans_data_lis_node`. Either worker could
   remove and free the other worker's node, lose an LDO/authentication event,
   misinterpret payload fields and corrupt queue counts. RX now owns its own
   list, spinlock and wait queue; TX retains its original queue.
2. RX used `list_add` and removed the first entry, reversing pending events.
   RX now appends to the tail, preserving delivery order. IRQ-map order is
   retained when the receiver reports multiple bits in one read.
3. CONNECT initialization sets wireless ICL to zero and runs through a business
   worker separate from the RX worker. An early LDO_ON could complete the normal
   current ramp before CONNECT overwrote it with zero. A session mutex now
   serializes initialization/reset against RX handling. Early RX nodes remain
   queued while offline and are woken after CONNECT initialization. Already
   queued RX nodes are discarded at disconnect.

These are reproduced source-level defects and plausible causes of lost charging
initialization. They are not proof that every power deficit reported on the
phone has the same cause. No current, voltage, FOD, temperature or protection
threshold has been increased or disabled.

## Verification

`wireless-followup-validation-20261125.json` records the source/object hashes.
Production C functions are extracted into host tests, with mocked hardware and
workqueue primitives. Both RX-first and TX-first processing preserve separate
ownership after the fix; the original source fails. FIFO order also fails on the
original source and passes after the fix. Early/late CONNECT and reconnect cases
pass. Existing command, authentication, temperature, power-supply, thermal, UFS
and release-label regressions pass.

The modified basic-wireless object and five thermal provider objects compile
for ARM64 using the normal three configuration fragments, host Clang 19.1.7,
CFI and MODVERSIONS. This is not a new full Image/module-modpost/Android build,
lockdep/KCSAN run or a hardware charging measurement. Use the ROM's configured
Android toolchain for production; do not copy host compiler paths into it.

## Thermal integration and outstanding qualification

The paired `android_device_xiaomi_myron` change adds already selected
`qcom-spmi-temp-alarm`, `qti_cpufreq_cdev`, `qti_devfreq_cdev`,
`qti_userspace_cdev` and `qti_dynamic_hw_trip` to normal Android vendor loading.
SCMI, IPC logging and PMIC providers already precede them in first-stage loading.
The effective Make variables and compiled ARM64 provider objects are checked.
Final vendor_dlkm contents, load success, DT binding, thermal HAL behavior and
SCMI firmware responses still need verification.

Other previously recorded gaps are not closed by this patch: connector thermal
zone binding, CNSS suspend vetoes, generic-PSCI versus optional QCOM LPM
qualification, firmware-dependent SCMI/PMIC messages, and device power HAL /
libperfmgr integration. Existing OCP/SPSS and IPA fixes are preserved; no claim of
new runtime validation is made for them. See `runtime-gap-status-20261122.md` for
those boundaries. No shared Evolution/Lineage build source is changed.

For the next device test, use a complete matching build, including the wireless
module in vendor_boot/vendor_dlkm and the new vendor thermal load list. A boot-only
flash does not install these changes. Compare battery charge counter over a
screen-off interval with the same charger and capture dmesg around insertion;
look for CONNECT followed by LDO_ON and nonzero `set wls_icl`, receiver voltage /
current and any thermal or input-suspend votes. A charging icon alone is not the
acceptance criterion.
