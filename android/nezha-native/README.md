# Xiaomi 17 Ultra kernel bring-up

Target: nezha, China OS4.0.7.0.XPACNXM. All three Git branches are named
`nazha`. The source baseline is 6.12.118. The OTA boot kernel is
`6.12.69-android16-6-g43b5ab7e247d-abogki561813157-4k` (4 KiB).
Its module ABI must be checked separately for any retained stock driver.

Use the three sibling project paths in manifest.xml. Include
`kernel/xiaomi/sm8850/android/nezha-native/BoardConfigKernel.mk` in the
nezha device BoardConfig for a source build. This fragment adds the touch
module directory to the product's existing external module selection.
The device tree still owns image assembly, first-stage fstab, vendor
ramdisk, module load lists, and any FORCE_PREBUILT settings.

In an Android kernel toolchain shell, from kernel/xiaomi/sm8850:

```sh
out="$PWD/../../../out/nezha/kernel"
make O="$out" ARCH=arm64 LLVM=1 gki_defconfig vendor/canoe_GKI.config vendor/nezha_GKI.config
make O="$out" ARCH=arm64 LLVM=1 -j8 Image dtbs modules
make -C ../sm8850-modules/xiaomi/nezha-touch KERNEL_SRC="$PWD" \
    M=../sm8850-modules/xiaomi/nezha-touch O="$out" ARCH=arm64 LLVM=1 modules
```

## OS4 image baseline

The five extracted images matched the SHA-256 values in the full OTA payload.

| Partition | Bytes | SHA-256 |
| --- | ---: | --- |
| boot | 100663296 | 1f7a147e34b6ca82621a194b3b6fa54735ae2236e34c65c42df41ec05422e832 |
| vendor_boot | 100663296 | 68a80b12e8210e0683fb0f275e0df2134db591113c9d6d91acbd34f54f4409cf |
| dtbo | 23068672 | 1b78a4cc5fe5ee46fcf1ea3af0ee5a1287c0b4a2ef78a30f4b62f745d31505ac |
| vendor_dlkm | 59228160 | 094b779c61c8b1736025230e545838001b0d4037ff2473dcbc413af128738cb4 |
| system_dlkm | 17281024 | b4177b860c3c99ccacf8e1fefb8584032ba214f61fe47e9f9cd78c4d3820d0d9 |

The v4 vendor_boot has one platform ramdisk fragment (22246717 bytes),
first_stage_ramdisk/fstab.qcom and 12 concatenated base DTBs. The early
ramdisk contains 471 modules, vendor_dlkm 404 and system_dlkm 206. These
counts describe separate partitions and can include the same module name.

## Device trees

Makefile.nezha orders the 12 source base targets like the vendor_boot DTB
section. The two input/NFC overlays implement the board wiring common to
the corresponding stock entries. Each reproduces 213 stock properties
(compared after resolving phandles) and adds explicit SPI address/size
cells and the DDIC strap GPIO descriptor. Both use Xiaomi board ID 5.
Treat these overlays as components during bring-up: the two original
entries include additional PMIC, charging, display, camera and audio data.
The full display overlay adds panel phandles to the touchscreen. Preserve
those links in a combined image. Panel firmware, trusted-touch VM, suspend
and all input devices still require hardware testing.

OS4 base canoep-tp / canoep-tp-v2 use SoC ID 0x1010295; the larger stock
overlay's list contains 0x1000295. Both original values are preserved.
Host fixup success alone cannot establish the bootloader selection for
these two variants. Verify the selected board and panel on hardware.
