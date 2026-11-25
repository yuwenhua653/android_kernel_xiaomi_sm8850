# Myron native source publication: Linux 6.12.118

The Linux 6.12.118 base update and retained platform fixes were published in
`3db85f696ae6cd550912c63a6c2251dd774b50a7`. Subsequent runtime hardening is
recorded in [the current gap report](runtime-gap-followup-20261125.md).
The current `manifest.xml` pairs the kernel branch with:

| Checkout | Branch | Commit |
| --- | --- | --- |
| `kernel/xiaomi/sm8850-modules` | `lineage-24.0` | `5638362f5eeb3cc0c8bbcd7d9cbf456e0fd9cc74` |
| `kernel/xiaomi/sm8850-devicetrees` | `lineage-24.0` | `fb892731a9b9df5ecd076409536d172e564b6850` |

The paired module revision also includes CNSS host-resume rollback after a
failed PCI-state save and the audio external-display symbol-table dependency.
The module update retains native Canoe video/MMRM integration, HFI brightness
transfers, deferred and incremental backlight fixes, RMNET external IPA APIs,
qce50/qcedev and SPU build entries, and SPSS resource/CMAC handling. The DT
update retains the wireless battery tables and generic-PSCI-v2 optional-consumer
policy alongside the existing touch SPI suspend fix. The idle overlay assumes
the reviewed Myron generic PSCI configuration, not the vendor LPM governor.

## Initial publication validation

The following describes the initial source publication. Existing validation
JSON files retain the source commits they originally checked. Consult the
current gap report for subsequent changes and their validation scope.

- The previously delivered 6.12.118 kernel content passed an ARM64 Image and
  349 in-tree module build with LLVM 19.1.7 and Rust 1.85.1. The published source
  was checked against that package and the retained source guards.
- The restored captured module source files match the November 17 source audit.
  The remaining native Kbuild entries come from the delivered repair packages.
- The Canoe video selection check covers all 42 translation units and flags.
  Production-function host tests passed for brightness transfers and the
  incremental gate; SPSS CMAC and probe/remove tests passed 13 and 9 scenarios.
- All 32 native DT inputs compiled with the 6.12.118 kernel headers. Applying
  the Myron board overlay to each of eight base DTBs passed the native idle
  checks and preserved three wireless tables per base. These checks do not
  assemble or validate the final ROM DTBO/vendor_boot images.

The complete external-module build against 6.12.118 with the Android toolchain,
module CRC/signature compatibility, final ROM images and device behavior still
require verification. The source publication workflow is not a build workflow.

## Integration scope

This publication updates only the three kernel-source checkouts. It does not
edit EvolutionX shared source or the Android device/vendor repositories.
Keep the existing Myron device-side module build and load lists, including
the SPU and securemsm chain, when integrating these sources. Rebuild the kernel
and all external modules together; do not reuse modules from 6.12.97.

The companion revisions in `manifest.xml` are pinned. A ROM checkout whose
local manifest still pins older commits must update those pins before syncing;
updating a GitHub branch alone does not override an existing manifest revision.

## Standard repository split

The three source histories are now published independently under
`yuwenhua653/android_kernel_xiaomi_sm8850`,
`yuwenhua653/android_kernel_xiaomi_sm8850-modules`, and
`yuwenhua653/android_kernel_xiaomi_sm8850-devicetrees`. All three repositories use `lineage-24.0` as their default branch.
The migration-only `main` branch is retained for provenance. The original `myron/native-*` branches remain available.

The new kernel repository starts from `3bc662f2695f21c7c4047826cd65b9a60d5408f9`.
The initial manifest migration changed repository addresses and branch references
only; checkout paths and the then-pinned companion commits were preserved. The original
`oppo_oplus_realme_sm8850` repository remains intact.
