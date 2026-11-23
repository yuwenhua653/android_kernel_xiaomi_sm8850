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

This is a confirmed software regression and a concrete candidate for the
first-logo boot failure. Host tests do not establish that it is the only
boot issue or that 6.12.118 now boots on hardware. Full Android-toolchain
rebuild of the affected module and corresponding images, followed by a
consistent image-set test, is still required. Do not mix new kernel images
with old system_dlkm/vendor_dlkm modules or disable verification as a fix.
