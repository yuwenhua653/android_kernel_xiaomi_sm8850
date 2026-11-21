# Xiaomi 17 Ultra kernel bring-up

Target: nezha, China OS4.0.7.0.XPACNXM. All three Git branches are named
`nazha`. The source baseline is 6.12.118. The OTA boot kernel is
`6.12.69-android16-6-g43b5ab7e247d-abogki561813157-4k` (4 KiB).
Its module ABI must be checked separately for any retained stock driver.

Use the three sibling project paths in manifest.xml. Include
`kernel/xiaomi/sm8850/android/nezha-native/BoardConfigKernel.mk` in the
nezha device BoardConfig for a source build. This fragment builds the display providers, MSM DRM and touch drivers
before the product's remaining external modules.
The device tree still owns image assembly, first-stage fstab, vendor
ramdisk, module load lists, and any FORCE_PREBUILT settings.

In an Android kernel toolchain Bash shell, from kernel/xiaomi/sm8850:

```sh
python3 ../sm8850-devicetrees/tools/prepare-nezha-display.py /path/to/OS4.0.7.0.XPACNXM/dtbo.img
out="$PWD/../../../out/nezha/kernel"
make O="$out" ARCH=arm64 LLVM=1 gki_defconfig vendor/canoe_GKI.config vendor/nezha_GKI.config
make O="$out" ARCH=arm64 LLVM=1 -j8 Image dtbs modules
for dir in qcom/opensource/mm-drivers/{msm_ext_display,sync_fence,hfi_core,hw_fence} \
           qcom/opensource/{securemsm-kernel,synx-kernel,display-drivers} xiaomi/nezha-touch; do
    make -j8 -C "../sm8850-modules/$dir" KERNEL_SRC="$PWD" \
        M="../sm8850-modules/$dir" O="$out" ARCH=arm64 LLVM=1 modules || exit 1
done
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
The combined Canoe target includes the input wiring and panel references together. Panel firmware, trusted-touch VM, suspend
and all input devices still require hardware testing.

OS4 base canoep-tp / canoep-tp-v2 use SoC ID 0x1010295; the larger stock
overlay's list contains 0x1000295. Both original values are preserved.
Host fixup success alone cannot establish the bootloader selection for
these two variants. Verify the selected board and panel on hardware.

## First native build

Clang 19.1.7 built a 34580992-byte arm64 4 KiB Image and all 14 DT targets.
The test machine used DWARF module versions and CFI; Android production
Rust and pahole were unavailable. The local Image SHA-256 was
0a9793613f10debf190a1dd316fcf302d25203450bc28970726f35ca5d2efc83.

The input overlays applied to all 12 corresponding factory bases and all
12 source bases in host fixup tests. Applying the *full* stock Canoe overlay
to the two CanoeP alternate thermal bases fails in libfdt. Those bases omit
11 referenced audio/DSP symbols, including canoe_snd and spf_core_platform.
This documents the original package combinations; successful application
of the smaller input overlays does not resolve whole-board selection.

Kbuild compiled ten in-tree dependency modules plus xiaomi_touch.ko and
synaptics_tcm2.ko. Strict modpost, the ROM-style external-module wrapper,
modules_install and a staged depmod check passed. All 112 version records
of xiaomi_touch and all 176 of synaptics_tcm2 matched the same-build exports.
Of the 15 Xiaomi framework symbols consumed by the stock controller, four
had different CRCs with this build and two were absent. Use the paired OSS
modules. This build covers the input stack and does not qualify every
factory module, the OS4 ROM packaging, or boot on a phone.


## OS4 display and touch

Run the preparation command above once per checkout. It checks the full
partition SHA-256 and writes a git-ignored DTS include next to the board
source. Kbuild adds `nezha-canoe-board-overlay.dtbo` when the include is
present. The generated file contains the panel settings from the local OTA.
A checkout without that input can still build the input and SoC targets.

For a **source** Canoe base, use this overlay order with the built
`scripts/dtc/fdtoverlay`. Example from the kernel tree after setting
`out` as above:

```sh
q="$out/arch/arm64/boot/dts/vendor/qcom"
"$out/scripts/dtc/fdtoverlay" -i "$q/canoe.dtb" -o "$out/nezha-canoe-display.dtb" \
    "$q/mm/hfi_core/canoe-hfi-core.dtbo" "$q/mm/hw_fence/canoe-hw-fence.dtbo" \
    "$q/synx/synx/canoe-synx.dtbo" "$q/nezha-canoe-display-soc.dtbo" \
    "$q/nezha-canoe-board-overlay.dtbo"
```

For the corresponding **factory** base, apply just the combined board overlay.
The six verified variants are canoe, canoe-v2, canoe-tp, canoe-tp-v2,
canoep and canoep-v2. The smaller SG/Whale entry keeps its own input target.
The SoC display layer preserves the factory-disabled HFI node and the two
extra unsecure SMMU reservations. The generic Canoe HFI layer enables the
node, which can make MSM DRM defer while waiting for HFI to probe.

Across the six factory and six source merges, all four screen clients
(touch, charge, thermal and fingerprint) resolved to the same ordered
list of ten panels as the factory result. The default was
`dsi_p1_42_02_0a_dsc_cmd`. All 115 panel subtree nodes, including
95 timing entries, matched in content after resolving handles. Timing order
matched as well. The board overlay reproduced 8,515 original properties
and the three native input additions. On each source base, 751 properties
from the SoC display, HFI, fence and synchronization overlays also matched.

The host built Image, 337 in-tree modules and 14 external modules. The
ROM-style wrappers installed all 351 in one staging tree. Strict modpost
and depmod passed. All external module version records matched the exports
from this build, including all 833 for msm_drm. Full module compilation
required restoring shared floor-rate clock operations and aligning CoreSight
registration and source callbacks with the APIs used on this branch.

The combined board overlay covers display and input. The Android product
still needs the other board subsystems, partition packaging and first-stage
load lists. Output here is for host integration. Hardware panel selection,
display power transitions, brightness, fingerprint and boot remain untested.
