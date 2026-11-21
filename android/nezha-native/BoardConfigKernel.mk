# SPDX-License-Identifier: GPL-2.0-only
# Include from the nezha BoardConfig after the common SM8850 configuration.
TARGET_KERNEL_SOURCE := kernel/xiaomi/sm8850
TARGET_KERNEL_CONFIG := gki_defconfig vendor/canoe_GKI.config vendor/nezha_GKI.config
BOARD_KERNEL_IMAGE_NAME := Image
TARGET_KERNEL_EXT_MODULE_ROOT := kernel/xiaomi/sm8850-modules
TARGET_KERNEL_EXT_MODULES += xiaomi/nezha-touch
