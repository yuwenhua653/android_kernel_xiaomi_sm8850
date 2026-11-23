# Xiaomi 17 Ultra kernel bring-up

Target: nezha, China OS4.0.7.0.XPACNXM. All three Git branches are named
`nazha`. The source baseline is 6.12.118. The OTA boot kernel is
`6.12.69-android16-6-g43b5ab7e247d-abogki561813157-4k` (4 KiB).
Its module ABI must be checked separately for any retained stock driver.

Use the three sibling project paths in manifest.xml. Include
`kernel/xiaomi/sm8850/android/nezha-native/BoardConfigKernel.mk` in the
nezha device BoardConfig for a source build. This fragment builds the native external module groups in dependency order.
The device tree still owns image assembly, first-stage fstab, vendor
ramdisk and any FORCE_PREBUILT settings. The optional OS4 module split is described below.

To build the kernel and its display/input subset in an Android kernel toolchain Bash shell, from kernel/xiaomi/sm8850:

```sh
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
ramdisk contains 471 modules, vendor_dlkm 404 and system_dlkm 103 distinct modules in two layouts (206 files). These
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

Kbuild builds `nezha-canoe-board-overlay.dtbo` directly from the checked-in
OS4.0.7.0.XPACNXM panel sources. The device-tree repository's
`qcom/display/display/nezha-sde-display.dtsi` includes the panel and pin
definitions from the same directory. A clean checkout contains all ten
panel configurations and their DSI commands and timings. The OTA extraction tool is optional for comparison with the factory
image.

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

## OS4.0.7 native module partitions

For a source bring-up product, include `BoardConfigModules.mk` immediately
after `BoardConfigKernel.mk` in the device BoardConfig. In the product
makefile use the normal Android product include:

```make
$(call inherit-product,kernel/xiaomi/sm8850/android/nezha-native/device.mk)
```

Select a source kernel, source-built system_dlkm and vendor_dlkm, and the
platform vendor ramdisk in the product. Remove conflicting prebuilt module
lists, prebuilt image selections and duplicate copy destinations when switching.
The stock OS4 platform ramdisk contains both load lists. The normal list
keeps first-stage order. Recovery adds xiaomi_touch ahead of synaptics_tcm2.
The staging list also includes their shared recovery/display providers.
Keep the product's first-stage fstab, firmware, AVB and partition settings.
The full Android product build and device boot still need validation.

| Load list | Unique factory entries | Matching modules in the host build | Entries shipped in native load list |
| --- | ---: | ---: | ---: |
| Normal first stage | 172 | 128 | 128 |
| Recovery | 465 | 242 | 244, including the native touch pair |
| vendor_dlkm | 404 | 181 | 181 |
| system_dlkm | 82 | 81 | 80, including production rust_binder |

The factory blocklist gives vendor ownership of zram and zsmalloc. The
native split packages them there only. The Android Rust-enabled config
also requires rust_binder in system_dlkm. The host used built-in C Binder
and validated 79 system load entries. Counts compare module basenames.
They do not establish which optional SoC variants or OEM hooks the phone uses.

The 6.12.118 build produced 352 in-tree and 75 external modules. All 8,098
external symbol version records matched same-build exports. Core Kbuild
rules and 15 platform drivers were restored from LineageOS/android_kernel_qcom_sm8850
commit `557159b6a0d06f1c6f07ec4c1f22bc9309a113e4`, using local EDAC headers.
The external build now includes IPA/RMNET, KGSL, audio, camera, video/EVA,
FastRPC, SPU, NFC, Bluetooth, CNSS and Peach v2 WLAN.

Host image readback verified 246 modules in the shared platform ramdisk,
100 in system_dlkm and 327 in vendor_dlkm. The two DLKM images used EROFS.
Every extracted module matched its staged ELF. The v4 vendor_boot round
trip preserved the stock fstab, concatenated DTB section and bootconfig
and contained one nonempty platform table entry. This packaging test uses
the factory base DTB section and does not qualify a production Android
image, module signing, firmware or hardware. That build preceded the regulator and MCA integration below. Other WLAN
variants remain to be ported.

## OS4 satellite supplies and MCA framework

The two board overlays use the same SE10 I2C bus, seven ET5907MV
outputs at address 0x35 and one HL7603 PA supply at 0x55. The latter
matches `tiantong,dcdc`. The separate MCA HL7603 boost chip has a
different binding. GPIO160 controls the shared PMIC enable and GPIO172
is the interrupt input. ET5907MV initializes the LDO selectors and
returns the shared pin to idle. The HL7603 driver leaves that pin under
board control. Its PA enable programs ILIM before setting bit 6. The
native drivers provide the Linux regulator interface. The factory
satellite character devices and their diagnostic sysfs ABI are still
outside this bring-up.

The Qualcomm MCA panel bridge and 15 core and class modules now build
for nezha. The PD node uses the factory 90 W parameter and the load
switch node stays disabled. These parameters describe the board. Actual
charging depends on the matching IC drivers, policy and firmware.
Register and voltage checks are offline. On the two low-voltage LDOs
the 800000 and 1300000 uV initial requests select 804000 and 1302000 uV
on the hardware grid. The future DXS702 consumer must allow these actual
voltages when using the Linux regulator API.

For Canoe use the overlay order above. For SG/Whale use
`nezha-sg-whale-board-overlay.dtbo` on its corresponding base. Both
include the supply wiring and MCA class nodes. The panel bridge needs an
active panel in the sibling charge-screen node before it can bind. Host checks merged the
board changes onto all 12 factory and 12 source bases. Across each merge
106 node properties for the regulators, pin states and MCA interfaces
matched the corresponding factory overlay, including the referenced pins.
This does not qualify bootloader selection on CanoeP thermal variants.

Normal first-stage coverage is now 130/172 factory module names.
Recovery covers 260/465 plus the two native touch modules. Vendor DLKM
covers 197/404. The `gpio-tiantong-dxs702` satellite GPIO consumer and OEM charging
policy still need source integration. The common MCA
symbols also differ between the native and factory stacks. Use matched
source-built consumers. In particular the fuel-gauge, charge-pump, buck
charger and PD operations still have factory-only interfaces.

The complete host build produced 370 in-tree and 75 external modules.
Readback found 264 matching ELFs in the v4 platform ramdisk, 100 in
system_dlkm and 345 in vendor_dlkm. All 360 imported symbol versions
on the 18 added modules and 8,098 on the external modules matched the
build's exports. The panel screen/HBM getters match the factory CRCs
and report primary-panel notifier state. The signed DT helper uses
the source kernel's device-node ABI. That build lacked 17 factory-exported names across the 16 MCA modules.
The subsequent Nezha PD update supplied USB vendor ID and Product VDO.
The native regulator interface still needs testing with the DXS702
consumer on hardware. No production Rust/AVB or device boot was tested.

## Main battery on Nezha

Both native board overlays describe the main gauge on QUP SE5 at I2C
address 0x55. The Linux BQ27Z561 driver publishes it as
`/sys/class/power_supply/battery` for Android Health. The recovery and
vendor_dlkm load lists include the core and I2C transport. SOC comes from
the gauge's relative state of charge. Current is in µA, remaining and
full charge are in µAh, and temperature is in tenths of a degree Celsius.
The gauge provides battery telemetry. Charger presence, thermal policy and
charge-pump control need their own providers.
