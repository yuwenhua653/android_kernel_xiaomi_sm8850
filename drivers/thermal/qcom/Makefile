# SPDX-License-Identifier: GPL-2.0-only

obj-$(CONFIG_QCOM_SPMI_ADC_TM5)	+= qcom-spmi-adc-tm5.o
obj-$(CONFIG_QCOM_SPMI_TEMP_ALARM)	+= qcom-spmi-temp-alarm.o
obj-$(CONFIG_QCOM_LMH)		+= lmh.o

# Qualcomm SM8850 platform modules.
# Platform drivers reference private in-tree headers by source-root paths.
ccflags-y += -I$(srctree)
ccflags-y += -I$(srctree)/drivers/thermal/qcom
obj-$(CONFIG_QTI_BCL_PMIC5) += bcl_pmic5.o
bcl_pmic5-y := qti_bcl_pmic5.o qti_bcl_stats.o
obj-$(CONFIG_QTI_CPU_HOTPLUG_COOLING_DEVICE) += cpu_hotplug.o
obj-$(CONFIG_QCOM_TSENS) += qcom_tsens.o
qcom_tsens-y := tsens-8960.o tsens-v0_1.o tsens-v1.o tsens-v2.o tsens.o
obj-$(CONFIG_QTI_CPU_PAUSE_COOLING_DEVICE) += thermal_pause.o

obj-$(CONFIG_QTI_DDR_COOLING_DEVICE) += ddr_cdev.o

obj-$(CONFIG_QTI_BCL_SOC_DRIVER) += bcl_soc.o

obj-$(CONFIG_QTI_CPUFREQ_CDEV) += qti_cpufreq_cdev.o
obj-$(CONFIG_QTI_DEVFREQ_CDEV) += qti_devfreq_cdev.o
obj-$(CONFIG_QTI_DYNAMIC_HW_THERMAL_TRIP) += qti_dynamic_hw_trip.o
obj-$(CONFIG_QTI_USERSPACE_CDEV) += qti_userspace_cdev.o
obj-$(CONFIG_QTI_QMI_COOLING_DEVICE) += qti_qmi_cdev.o
qti_qmi_cdev-y := qmi_cooling.o thermal_mitigation_device_service_v01.o
obj-$(CONFIG_QTI_QMI_SENSOR_V2) += qti_qmi_sensor_v2.o
qti_qmi_sensor_v2-y := qmi_sensors_v2.o thermal_sensor_service_v02.o
obj-$(CONFIG_QTI_THERMAL_VENDOR_HOOK) += qti_thermal_vendor_hooks.o
