# SPDX-License-Identifier: GPL-2.0

# Qualcomm SM8850 platform modules.
# Platform drivers reference private in-tree headers by source-root paths.
ccflags-y += -I$(srctree)
ccflags-y += -I$(srctree)/drivers/misc/hwid -I$(srctree)/drivers/power/supply/mca/include -I$(srctree)/drivers/power/supply/mca/mca_common -I$(srctree)/include
obj-$(CONFIG_XIAOMI_MCA_ADSP_PD) += mca_adsp_glink.o
obj-$(CONFIG_XIAOMI_MCA_CHARGE_INTERFACE) += mca_charge_interface.o
obj-$(CONFIG_MYRON_MCA_PLATFORM) += mca_charge_mievent.o
obj-$(CONFIG_XIAOMI_MCA_CORE) += mca_event.o
obj-$(CONFIG_MCA_QCOM_PANEL) += mca_qcom_panel.o
obj-$(CONFIG_XIAOMI_MCA_CORE) += mca_hwid.o
obj-$(CONFIG_XIAOMI_MCA_CORE) += mca_log.o
obj-$(CONFIG_XIAOMI_MCA_CORE) += mca_parse_dts.o
obj-$(CONFIG_MYRON_MCA_PLATFORM) += mca_qcom_smem.o
obj-$(CONFIG_XIAOMI_MCA_CORE) += mca_sysfs.o
obj-$(CONFIG_XIAOMI_MCA_CORE) += mca_voter.o
obj-$(CONFIG_XIAOMI_MCA_CORE) += mca_workqueue.o
