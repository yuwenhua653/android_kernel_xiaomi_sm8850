# Myron 6.12.118 UFS PHY clock-gating regression

The 6.12.97 baseline uses `ufs_qcom_phy_power_off()` in the inactive-link
PRE_CHANGE path. This vendor helper serializes the transition with
`phy_mutex`, calls the generic PHY API only if powered, and clears
`is_phy_pwr_on`. POST_CHANGE/on uses its paired vendor power-on helper.

The 6.12.118 integration additionally called raw `phy_power_off()` after
the inactive-link conditional. This mixes the upstream generic PHY path
with the vendor driver's existing state machine:

- On Hibern8/off links, the helper drops power_count from 1 to 0; the extra
  call decrements it again to -1 and drops a second runtime-PM reference.
  On the next power-on, PHY core sees a nonzero count, skips the hardware
  power-on callback and increments the count to 0, while the vendor flag
  becomes true. The controller can subsequently access an unpowered PHY.
- On an active link, the raw call powers down the PHY while leaving the
  vendor flag true. The next vendor power-on helper then skips restoration.

Remove only that additional raw call and document ownership by the vendor
helpers. Keep the original link-state gate, mutex, clocks, refclk, bandwidth,
QoS and POST_CHANGE power-on sequence. Retain the separate reset-settling
change and other LTS updates.

## Evidence

The supplied old/new `ufs-qcom.ko` files contain one/two relocations to
`phy_power_off` inside `ufs_qcom_setup_clocks`, respectively. Their
vermagic matches their respective 6.12.97/6.12.118 kernels. This demonstrates
that the bad path is in the failing build, not just in an unused source file.
The reviewed Myron merged DT selects `qcom,ufshc`; the driver has clock
gating and Hibern8-with-clock-gating support.

Old/new vendor_boot base DTBs and bootconfig are identical; the extracted
phone DTBO applies to all eight bases. The initial ramdisk executable,
fstab and module load lists do not introduce a new functional difference.
The extracted current vbmeta has Flags=3; failure cannot be attributed to
omitting vbmeta regeneration alone. These observations do not reconstruct
all partitions present during the failed boot.

## Regression validation

`python3 android/myron-native/tests/test_ufs_phy_balance.py` compiles the
actual production `ufs_qcom_setup_clocks`, vendor PHY helpers and generic
PHY power-on/off functions with mocked hardware under UBSan. The corrected
source passes 1536 clock/power cycles, repeated requests, active-link
retention, Hibern8/off transitions, power/PM/regulator errors and pre-init
calls. The uncorrected source fails the power_count assertion both in the
active-link case and when the active case is omitted to reach Hibern8.

## Cloud build and device follow-up (2026-11-23)

The r3 baseline plus this UFS correction completed an ARM64 `Image modules`
build using the supplied image's exact configuration and Android Clang
r563880c, Rust 1.93.1, bindgen 0.72.0 and pahole 1.25. All 18,259 kernel export
CRCs matched the supplied 6.12.118 image. The corrected UFS module's 222
import CRCs, KCFI external type IDs and dependency set also matched.

The controlled test package retained the supplied 6.12.118 core Image and
other modules. Its UFS module BTF was generated against the shipped core's
BTF; all three copies in vendor_boot, recovery and vendor_dlkm were replaced.
Ramdisk metadata, EROFS labels, DTB, DTBO and load lists were preserved, and
affected AVB descriptors were regenerated without changing the existing
verification flags. The user subsequently reported that the device boots.

This supports the UFS regression as a cause of the first-logo failure. It is
not a claim that all remaining hardware behavior is validated. A new full
native ROM build using a different release label must rebuild the core and
all modules together; the controlled test does not qualify mixing those
outputs with the old module images. The later -yuzuli naming policy changes
release metadata only, not GKI architecture, CFI or AVB policy.
