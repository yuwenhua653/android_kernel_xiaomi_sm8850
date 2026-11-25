# SPDX-License-Identifier: GPL-2.0-only
# Include from the nezha BoardConfig after the common SM8850 configuration.
TARGET_KERNEL_SOURCE := kernel/xiaomi/sm8850
TARGET_KERNEL_CONFIG := gki_defconfig vendor/canoe_GKI.config vendor/nezha_GKI.config
BOARD_KERNEL_IMAGE_NAME := Image
TARGET_KERNEL_EXT_MODULE_ROOT := kernel/xiaomi/sm8850-modules
# Build these dependencies before display-drivers and any product-specific consumers.
nezha_display_modules := $(addprefix qcom/opensource/, \
    mm-drivers/msm_ext_display mm-drivers/sync_fence mm-drivers/hfi_core \
    mm-drivers/hw_fence securemsm-kernel synx-kernel display-drivers)
nezha_native_modules := $(nezha_display_modules) xiaomi/nezha-touch \
    qcom/opensource/datarmnet-ext/mem \
    qcom/opensource/dataipa \
    qcom/opensource/datarmnet \
    qcom/opensource/datarmnet-ext/shs \
    qcom/opensource/datarmnet-ext/perf \
    qcom/opensource/datarmnet-ext/offload \
    qcom/opensource/datarmnet-ext/perf_tether \
    qcom/opensource/datarmnet-ext/wlan \
    qcom/opensource/datarmnet-ext/aps \
    qcom/opensource/datarmnet-ext/sch \
    qcom/opensource/data-kernel/drivers/smem-mailbox \
    qcom/opensource/mmrm-driver \
    qcom/opensource/video-driver \
    qcom/opensource/spu-kernel \
    qcom/opensource/graphics-kernel \
    nxp/opensource/driver st/opensource/driver \
    qcom/opensource/dsp-kernel \
    qcom/opensource/audio-kernel \
    qcom/opensource/wlan/platform \
    qcom/opensource/bt-kernel \
    qcom/opensource/eva-kernel \
    qcom/opensource/camera-kernel \
    qcom/opensource/wlan/qcacld-3.0
TARGET_KERNEL_EXT_MODULES := $(nezha_native_modules) \
    $(filter-out $(nezha_native_modules) $(addsuffix :kbuild,$(nezha_native_modules)),$(TARGET_KERNEL_EXT_MODULES))
