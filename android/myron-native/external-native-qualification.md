# Complete native external-module qualification

Qualified kernel source: `d199ff171e49e1b1e4c62fa7202c146e76b26e3b`.
Qualified module source: `5638362f5eeb3cc0c8bbcd7d9cbf456e0fd9cc74`.
Paired device source: `83bb1e170ff8755205bb436ca21ca4967002fc41`.

## Integration corrections

The device repository's `evolution.dependencies` and `kernel/local_manifest.xml`
still selected the legacy `oppo_oplus_realme_sm8850` branches. They now select
the three published Xiaomi repositories, preserving checkout paths. Both kernel
and device manifest templates pin the corrected companion module commit. This
repairs new-checkout/template sync inputs; it does not rewrite an existing WSL
local manifest. Shared EvolutionX sources and libperfmgr remain unchanged.

Full audio modpost found two unresolved HDMI imports even though the display
provider was already built: `msm_ext_disp_register_audio_codec` and
`msm_ext_disp_select_audio_codec`. The audio Kbuild now explicitly includes
`../mm-drivers/msm_ext_display/Module.symvers`, matching the declared native build
order. The pre-fix failure was reproduced; the corrected group and all subsequent
groups link successfully. No driver function, charging limit or thermal threshold
was changed in this checkpoint.

## Build result

Every one of the 25 groups in the current device `TARGET_KERNEL_EXT_MODULES`
list reaches final `.ko` linking and modpost, without unresolved-symbol warnings.
This includes the complete WLAN, camera, audio, DSP, graphics/display and video
source sets, not just previously modified objects. All 6,316 selected tracked
external build inputs match their committed Git blobs.

| Native external group | Linked modules |
| --- | ---: |
| `qcom/opensource/mm-drivers/msm_ext_display` | 1 |
| `qcom/opensource/mm-drivers/hfi_core` | 1 |
| `qcom/opensource/mm-drivers/hw_fence` | 1 |
| `qcom/opensource/mm-drivers/sync_fence` | 1 |
| `qcom/opensource/audio-kernel` | 34 |
| `qcom/opensource/dsp-kernel` | 1 |
| `qcom/opensource/mmrm-driver` | 1 |
| `qcom/opensource/synx-kernel` | 2 |
| `qcom/opensource/securemsm-kernel` | 5 |
| `qcom/opensource/spu-kernel` | 2 |
| `qcom/opensource/datarmnet-ext/mem` | 1 |
| `qcom/opensource/dataipa` | 2 |
| `qcom/opensource/datarmnet` | 2 |
| `qcom/opensource/datarmnet-ext/shs` | 1 |
| `qcom/opensource/datarmnet-ext/perf` | 1 |
| `qcom/opensource/data-kernel/drivers/smem-mailbox` | 1 |
| `nxp/opensource/driver` | 1 |
| `qcom/opensource/camera-kernel` | 1 |
| `qcom/opensource/graphics-kernel` | 1 |
| `qcom/opensource/display-drivers` | 1 |
| `qcom/opensource/eva-kernel` | 1 |
| `qcom/opensource/video-driver` | 1 |
| `qcom/opensource/wlan/platform` | 6 |
| `qcom/opensource/bt-kernel` | 3 |
| `qcom/opensource/wlan/qcacld-3.0` | 1 |

Total: 73 external modules plus 354 in-tree modules. The read-only checker
validates all 427 ELF64/ARM64 modules, 25,516 recorded symbol CRCs, providers,
declared dependencies and matching vermagic. The six expanded Make packaging/load
groups have no missing or duplicate names. All 314 modules selected by the device's
packaging input list are present. These are input/output-directory checks, not
verification of final partition image contents.

Six real-artifact negative controls reject changed CRCs, absent exports, wrong
kernel release, duplicate modules, absent dependency modules and duplicate export
providers. Extended modversions parsing passes a positive check; five malformed
ELF/version inputs are rejected. Detailed hashes, module records, packaging groups,
source IDs and build warnings are retained in `external-native-validation.json`.

## Repeating the read-only check

After the standard ROM/native build, pass its actual kernel output and every
external output root whose `Module.symvers` and `modules.order` were produced by
that build. Repeat `--external-out` for every provider/consumer root in the set.
Missing dependencies are errors; do not omit them to obtain a passing result.

```sh
python3 kernel/xiaomi/sm8850/android/myron-native/check_module_versions.py \
  --kernel-out <actual-KERNEL_OBJ> \
  --external-out <actual-external-output-root> \
  --json <report.json>
```

These are placeholders for existing output paths. The script reads uncompressed
`.ko` files from `modules.order`; it does not build, install, modify, sign or load
modules. Basic ARM64 and extended modversions are supported. It supplements
modpost; it is not a complete KMI or module-signature verifier.

## Qualification boundary

This reused the existing Clang 19.1.7 qualification output with CFI and
MODVERSIONS, LTO_NONE, no Rust/BTF, and kernel release
`6.12.118-g9a7946c166d3-yuzuli`. That identifies the previously built core plus
the subsequently published working-tree changes recorded in
`wireless-apply-validation.json`. External makes explicitly retained that output's
KERNELRELEASE. This is not a production ROM build or flashable release. No
production Kconfig or version-generation rule was altered for qualification.

The Android production toolchain/configuration, final partition images, module
signatures/loading, actual suspend behavior, thermal-policy/firmware matching and
net wireless battery charging remain unverified here. Previous charging fixes
are retained; compilation is not evidence of hardware charging success.
