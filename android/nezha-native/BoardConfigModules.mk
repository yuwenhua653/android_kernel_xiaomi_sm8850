# SPDX-License-Identifier: GPL-2.0-only
# Include after BoardConfigKernel.mk when staging the native OS4 module split.
nezha_module_lists := $(TARGET_KERNEL_SOURCE)/android/nezha-native
BOARD_USES_SYSTEM_DLKMIMAGE := true
BOARD_USES_VENDOR_DLKMIMAGE := true
TARGET_AUTO_COLLECT_KERNEL_MODULE_DEPS := true

BOARD_VENDOR_RAMDISK_KERNEL_MODULES_LOAD := $(strip $(shell cat $(nezha_module_lists)/modules.load.vendor_boot))
BOARD_RECOVERY_KERNEL_MODULES_LOAD := $(strip $(shell cat $(nezha_module_lists)/modules.load.recovery))
BOARD_SYSTEM_KERNEL_MODULES_LOAD := $(strip $(shell cat $(nezha_module_lists)/modules.load.system_dlkm))
BOARD_VENDOR_KERNEL_MODULES_LOAD := $(strip $(shell cat $(nezha_module_lists)/modules.load.vendor_dlkm))
SYSTEM_KERNEL_MODULES := $(strip $(shell cat $(nezha_module_lists)/modules.list.system_dlkm))

# Both boot modes use the same platform ramdisk. Package their union, including
# the HDCP and SMMU providers, while keeping each boot mode's load order.
RECOVERY_KERNEL_MODULES := $(BOARD_RECOVERY_KERNEL_MODULES_LOAD) \
    $(strip $(shell cat $(nezha_module_lists)/modules.list.ramdisk_deps))
BOOT_KERNEL_MODULES := $(sort $(BOARD_VENDOR_RAMDISK_KERNEL_MODULES_LOAD) $(RECOVERY_KERNEL_MODULES))
