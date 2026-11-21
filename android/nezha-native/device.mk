# SPDX-License-Identifier: GPL-2.0-only
# Android first-stage init selects modules.load.recovery from this same ramdisk.
PRODUCT_COPY_FILES += \
    kernel/xiaomi/sm8850/android/nezha-native/modules.load.recovery:$(TARGET_COPY_OUT_VENDOR_RAMDISK)/lib/modules/modules.load.recovery
