# 小米 17 Ultra OSS 内核未完成清单

国行 nezha，分支 nazha，基线 OS4.0.7.0.XPACNXM。本次主机验证使用 Linux 6.12.118、ARM64 4 KiB 和 Clang 19。

## 模块覆盖

| 原厂加载清单 | 原厂去重名称 | 已编出同名模块 | 未编出同名模块 |
|---|---:|---:|---:|
| 启动 | 172 | 130 | 42 |
| 恢复 | 465 | 262 | 203 |
| Vendor | 404 | 209 | 195 |
| System | 82 | 81 | 1 |

四份原厂加载清单合计 **655 个不同模块名**，本次构建覆盖 **417 个**，余 **238 个**。启动盘、vendor_dlkm 和 system_dlkm 镜像内共 676 个不同模块名，另有 21 个只随包交付，均已有同名构建产物。覆盖按本次暂存目录中的 .ko 文件统计；硬件功能另列实机验证。

zram.ko 和 zsmalloc.ko 均已编出，原生分区方案将它们放在 vendor 侧。rust_binder.ko 已列入原生 system 清单，本轮使用内置 C Binder，生产 Rust 配置仍待构建。原生 vendor 清单共 211 项，含提供电量计的两个通用 bq27xxx 模块。

## 接下来要完成的工作

| 工作 | 完成依据 |
|---|---|
| 生产内核与首次开机 | 用 Android 生产工具链验证 Rust Binder、模块签名及最终镜像。用 17 Ultra 验证 first-stage、DLKM 挂载、模块加载与进入系统。 |
| 供电与充电 | 核对主电量计、充电器插拔、温控及过流保护，验证 Android Health 的在线状态、电流方向和温度。快充、无线充电及反向供电各自需要确认芯片和策略。 |
| 首阶段外设 | 优先排查 DXS702 卫星 GPIO、ET5907MV / HL7603 电源依赖与绑定。依据 probe 日志判定对启动的影响。 |
| 数据网络与 USB | 本轮已编出 ipanetm.ko。待验证 WWAN 注册、移动数据、RNDIS/NCM 共享、断线重连及 modem 子系统重启。Wi-Fi 依硬件 ID 选择 Peach v2、Kiwi v2 或 WCN7750。 |
| 17 Ultra 多媒体与输入 | 验证相机多摄切换、镜头环、音频路由、麦克风、振动、显示/触控休眠唤醒及指纹。按实机选用功放、编解码器、NFC 等变体。 |
| 待机与小米专用服务 | 以休眠、唤醒源、温控及功耗测试筛选必要接口。Millet 策略、性能统计、追踪与测试模块按实际调用方取舍。 |

## 全部 238 项

每行一个缺少同名产物的模块。正常首阶段项排在前面，位置列保留所有出现的原厂加载清单。构建线索来自当前源码中的同名直接 obj-* 声明；空栏仍需查 Kconfig、DDK 声明、文件改名或其他来源。有声明的模块同样需要核对板级适用性。

| 模块 | 原厂加载位置 | 同名构建线索 | 备注 |
|---|---|---|---|
| `binder_gki.ko` | 启动、恢复 |  | 核对厂商扩展调用方，本轮标准 Binder 已内置 |
| `bootinfo.ko` | 启动、恢复 |  |  |
| `boottime.ko` | 启动、恢复 |  |  |
| `common.ko` | 启动、恢复 | 内核 / arch/arm/mach-davinci/Makefile |  |
| `cpq.ko` | 启动、恢复 |  |  |
| `debug_ext.ko` | 启动、恢复 |  |  |
| `dio_dma_mapper.ko` | 启动、恢复 |  |  |
| `dynamic_readahead.ko` | 启动、恢复 |  |  |
| `fault_report.ko` | 启动、恢复 |  |  |
| `gpio-tiantong-dxs702.ko` | 启动、恢复 |  | 优先核对卫星 GPIO 消费者、供电顺序及其子设备 |
| `gpu_stats.ko` | 启动、恢复 |  |  |
| `iorap2.ko` | 启动、恢复 |  |  |
| `mem_fault_events.ko` | 启动、恢复 |  |  |
| `mi-power.ko` | 启动、恢复 |  |  |
| `mi_damon.ko` | 启动、恢复 |  |  |
| `mi_extent_pool.ko` | 启动、恢复 |  |  |
| `mi_game.ko` | 启动、恢复 |  |  |
| `mi_memory.ko` | 启动、恢复 |  |  |
| `mi_mempool.ko` | 启动、恢复 |  |  |
| `mi_proc_exit.ko` | 启动、恢复 |  |  |
| `mi_qmi_trace.ko` | 启动、恢复 |  |  |
| `mi_wq_dynamic_priority.ko` | 启动、恢复 |  |  |
| `millet_binder.ko` | 启动、恢复 |  | 小米 Millet 策略，按类原生用户空间依赖取舍 |
| `millet_core.ko` | 启动、恢复 |  |  |
| `millet_hs.ko` | 启动、恢复 |  |  |
| `millet_oem_cgroup.ko` | 启动、恢复 |  |  |
| `millet_pkg.ko` | 启动、恢复 |  |  |
| `millet_sig.ko` | 启动、恢复 |  |  |
| `mimon.ko` | 启动、恢复 |  |  |
| `mist.ko` | 启动、恢复 |  |  |
| `os_cpu_qi.ko` | 启动、恢复 |  |  |
| `os_cpu_qs.ko` | 启动、恢复 |  |  |
| `perf_actuator.ko` | 启动、恢复 |  |  |
| `perf_helper.ko` | 启动、恢复 |  |  |
| `plat_common.ko` | 启动、恢复 |  |  |
| `powerinsight_interface.ko` | 启动、恢复 |  |  |
| `rtg.ko` | 启动、恢复 |  |  |
| `scene_swappiness.ko` | 启动、恢复 |  |  |
| `swinfo.ko` | 启动、恢复 |  |  |
| `unfairmem.ko` | 启动、恢复 |  |  |
| `vip_sched.ko` | 启动、恢复 |  |  |
| `xm_usb_pri_interface.ko` | 启动、恢复 |  |  |
| `adsp_sleepmon.ko` | 恢复、Vendor |  |  |
| `aw882xx_dlkm.ko` | Vendor |  |  |
| `boot_stats.ko` | 恢复、Vendor |  |  |
| `bootmonitor.ko` | 恢复、Vendor |  |  |
| `bq27z561.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_hardware_ic/fuelgauge_ic/bq27z561/Makefile | 已有 bq27xxx 电量计路径，核验 Android Health 读数及剩余接口 |
| `btfm_slim_codec.ko` | Vendor | 外置模块 / qcom/opensource/bt-kernel/slimbus/Makefile |  |
| `bwmon.ko` | 恢复、Vendor |  |  |
| `cameralog.ko` | Vendor |  |  |
| `cameramsger.ko` | Vendor |  |  |
| `cdsprm.ko` | 恢复、Vendor |  |  |
| `charger-ulog-glink.ko` | 恢复、Vendor |  |  |
| `charger_partition.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_shared_memory/Makefile |  |
| `cl_dsp-core.ko` | 恢复、Vendor |  |  |
| `core_hang_detect.ko` | 恢复、Vendor |  |  |
| `coresight-csr.ko` | 恢复、Vendor |  |  |
| `coresight-qmi.ko` | 恢复、Vendor |  |  |
| `coresight-remote-etm.ko` | 恢复、Vendor |  |  |
| `coresight-tgu.ko` | 恢复、Vendor |  |  |
| `coresight-tmc-sec.ko` | 恢复、Vendor |  |  |
| `coresight-trace-noc.ko` | 恢复、Vendor |  |  |
| `coresight-uetm.ko` | 恢复、Vendor |  |  |
| `cpu_mpam.ko` | 恢复、Vendor |  |  |
| `cpucp_log.ko` | 恢复、Vendor |  |  |
| `cs40l26-core.ko` | 恢复、Vendor |  | 核对振动器型号、供电与固件 |
| `cs40l26-i2c.ko` | 恢复、Vendor |  |  |
| `dcc_v2.ko` | 恢复、Vendor |  |  |
| `dmesg_dumper.ko` | 恢复、Vendor |  |  |
| `dump_binder.ko` | 恢复、Vendor |  |  |
| `dump_display.ko` | 恢复、Vendor |  |  |
| `f_fs_ipc_log.ko` | 恢复、Vendor |  |  |
| `focus_ring_bridge.ko` | Vendor |  | 核对 17 Ultra 镜头环事件与 Android 输入映射 |
| `ftun.ko` | Vendor |  |  |
| `gh_ctrl.ko` | 恢复、Vendor |  |  |
| `gh_panic_notifier.ko` | 恢复、Vendor |  |  |
| `gh_rm_booster.ko` | 恢复、Vendor |  |  |
| `gh_tlmm_vm_mem_access.ko` | 恢复、Vendor |  |  |
| `glink_probe.ko` | 恢复、Vendor |  |  |
| `gpio-mi-t1.ko` | 恢复、Vendor |  |  |
| `gpu_freq_stats.ko` | 恢复、Vendor |  |  |
| `gunyah_trace.ko` | 恢复、Vendor |  |  |
| `hangdetect.ko` | 恢复、Vendor |  |  |
| `hardwareinfo.ko` | Vendor |  |  |
| `heap_mem_ext_v01.ko` | 恢复、Vendor |  |  |
| `hl7603.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_hardware_ic/boost_ic/hl7603/Makefile | 已有 HL7603 卫星 PA 稳压器实现，充电侧绑定另行核验 |
| `hung_task_enh.ko` | 恢复、Vendor |  |  |
| `hvc_gunyah.ko` | 恢复、Vendor |  |  |
| `hypsys_netlink.ko` | 恢复、Vendor |  |  |
| `i3c-master-msm-geni.ko` | 恢复、Vendor |  |  |
| `icnss2.ko` | Vendor | 外置模块 / qcom/opensource/wlan/platform/icnss2/Makefile |  |
| `io_monitor.ko` | 恢复、Vendor |  |  |
| `ipclite_test.ko` | Vendor | 外置模块 / qcom/opensource/synx-kernel/msm/Kbuild |  |
| `ir-spi.ko` | 恢复、Vendor | 内核 / drivers/media/rc/Makefile |  |
| `jtag-io.ko` | 恢复、Vendor |  |  |
| `leds-qpnp-vibrator-ldo.ko` | 恢复、Vendor |  |  |
| `llcc_heuristics.ko` | 恢复、Vendor |  |  |
| `lmh_stats.ko` | 恢复、Vendor |  |  |
| `lt9611uxc.ko` | 恢复、Vendor |  |  |
| `matt.ko` | Vendor |  |  |
| `mca_basic_wireless.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_strategy/strategy_wireless/Makefile |  |
| `mca_bmd.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_hardware_monitor/Makefile |  |
| `mca_buckchg_jeita.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_strategy/strategy_charger/Makefile |  |
| `mca_business_battery_comp.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_business/business_battery/Makefile |  |
| `mca_business_charger_comp.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_business/business_charger/Makefile |  |
| `mca_business_misc_comp.ko` | 恢复、Vendor |  |  |
| `mca_charge_interface.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_common/Makefile | 核对 Android Health 所需充电状态和电源接口 |
| `mca_charge_mievent.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_common/Makefile |  |
| `mca_charger_thermal.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_strategy/strategy_charger/Makefile | 核对充电温控和限流路径 |
| `mca_connector_antiburn.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_hardware_monitor/Makefile | 核对接口温度监测及保护策略 |
| `mca_ibat_ocp_monitor.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_hardware_monitor/Makefile |  |
| `mca_lpd_detect.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_hardware_monitor/Makefile |  |
| `mca_path_control.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_hardware_monitor/Makefile |  |
| `mca_pd_auth.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_strategy/strategy_pd/Makefile |  |
| `mca_platform_base.ko` | 恢复、Vendor |  |  |
| `mca_platform_wireless_class.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_platform/Makefile |  |
| `mca_qcom_smem.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_common/Makefile |  |
| `mca_qcom_subpmic_proxy.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_qcom_subpmic_proxy/Makefile | 核对充电器接入状态及 ADSP 属性映射 |
| `mca_qcom_sysfs.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_qcom_sysfs/Makefile |  |
| `mca_quick_wireless.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_strategy/strategy_wireless/Makefile |  |
| `mca_smart_charge.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_smart_charge/Makefile |  |
| `mca_strategy_buckchg.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_strategy/strategy_charger/Makefile |  |
| `mca_strategy_class.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_strategy/Makefile |  |
| `mca_strategy_fg_class.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_strategy/strategy_fg/Makefile |  |
| `mca_strategy_fg_comp.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_strategy/strategy_fg/Makefile |  |
| `mca_strategy_quickchg.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_strategy/strategy_charger/Makefile |  |
| `mca_vbat_ovp_monitor.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_hardware_monitor/Makefile |  |
| `mca_wireless_revchg.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_strategy/strategy_wireless/Makefile |  |
| `mem-hooks.ko` | 恢复、Vendor |  |  |
| `mem-offline.ko` | 恢复、Vendor |  |  |
| `memlat.ko` | 恢复、Vendor |  |  |
| `mhi_dev_satellite.ko` | 恢复、Vendor |  |  |
| `mhi_dev_uci.ko` | 恢复、Vendor |  |  |
| `mi_cam.ko` | Vendor |  | 核对 17 Ultra 相机 HAL 实际调用的接口 |
| `mi_dma_dio.ko` | 恢复、Vendor |  |  |
| `mi_low_lat_mem.ko` | 恢复、Vendor |  |  |
| `mi_memcheck.ko` | 恢复、Vendor |  |  |
| `mi_ntsync.ko` | 恢复、Vendor |  |  |
| `mi_reclaim.ko` | 恢复、Vendor |  |  |
| `mi_stack.ko` | 恢复、Vendor |  |  |
| `mi_thermal_interface.ko` | 恢复、Vendor |  |  |
| `mi_trace.ko` | 恢复、Vendor |  |  |
| `mi_ubt.ko` | 恢复、Vendor |  |  |
| `mi_ubt_test.ko` | 恢复、Vendor |  |  |
| `mi_wmark.ko` | 恢复、Vendor |  |  |
| `mibbr.ko` | Vendor |  |  |
| `microdump_collector.ko` | 恢复、Vendor |  |  |
| `miicmpfilter.ko` | Vendor |  |  |
| `minet.ko` | Vendor |  |  |
| `miscore.ko` | Vendor |  |  |
| `mitee_dlkm.ko` | Vendor |  |  |
| `mpam.ko` | 恢复、Vendor |  |  |
| `mpam_msc.ko` | 恢复、Vendor |  |  |
| `mpam_msc_slc.ko` | 恢复、Vendor |  |  |
| `msm_memshare.ko` | 恢复、Vendor |  |  |
| `msm_show_epoch.ko` | 恢复、Vendor |  |  |
| `msm_show_resume_irq.ko` | 恢复、Vendor |  |  |
| `mtdoops.ko` | 恢复、Vendor | 内核 / drivers/mtd/Makefile |  |
| `node_cache.ko` | 恢复、Vendor |  |  |
| `nuvolta_1671.ko` | 恢复、Vendor |  | 依板级 I²C 绑定、电源拓扑和固件确认对应充电 IC |
| `pci_phy_access.ko` | 恢复、Vendor |  |  |
| `phy-msm-snps-eusb2.ko` | 恢复、Vendor |  |  |
| `phy-qcom-emu.ko` | 恢复、Vendor |  |  |
| `phy-qcom-m31-eusb2.ko` | 恢复、Vendor |  |  |
| `pinctrl-spmi-mpp.ko` | 恢复、Vendor |  |  |
| `platform_mpam.ko` | 恢复、Vendor |  |  |
| `pmic-glink-debug.ko` | 恢复、Vendor |  |  |
| `powersave.ko` | 恢复、Vendor | 内核 / arch/powerpc/platforms/pasemi/Makefile |  |
| `printk_enhance.ko` | 恢复、Vendor |  |  |
| `qca_cld3_kiwi_v2.ko` | Vendor |  | 已有 Peach v2 产物，按实机 WLAN 硬件 ID 核对 |
| `qca_cld3_wcn7750.ko` | Vendor |  | 已有 Peach v2 产物，按实机 WLAN 硬件 ID 核对 |
| `qcom-amoled-regulator.ko` | 恢复、Vendor |  |  |
| `qcom-cpufreq-hw-debug.ko` | 恢复、Vendor |  |  |
| `qcom-i2c-pmic.ko` | 恢复、Vendor |  |  |
| `qcom-pmic-ecid.ko` | 恢复、Vendor |  |  |
| `qcom_cpuss_sleep_stats.ko` | 恢复、Vendor |  |  |
| `qcom_dynamic_ramoops.ko` | 恢复、Vendor |  |  |
| `qcom_fdcvs.ko` | 恢复、Vendor |  |  |
| `qcom_lpm.ko` | 恢复、Vendor |  |  |
| `qcom_lpm_monitor.ko` | 恢复、Vendor |  |  |
| `qcom_voltage_adj.ko` | 恢复、Vendor |  |  |
| `qmp_dlkm.ko` | Vendor |  |  |
| `qpnp-lcdb-regulator.ko` | 恢复、Vendor |  |  |
| `qptf.ko` | 恢复、Vendor |  |  |
| `qrtr-gunyah.ko` | 恢复、Vendor |  |  |
| `qsee_ipc_irq_bridge.ko` | 恢复、Vendor |  |  |
| `qti-glink-adc.ko` | 恢复、Vendor |  |  |
| `qti_amoled_ecm.ko` | 恢复、Vendor |  |  |
| `qti_battery_debug.ko` | 恢复、Vendor |  |  |
| `qti_btl.ko` | 恢复、Vendor |  |  |
| `qti_cpufreq_cdev.ko` | 恢复、Vendor |  |  |
| `qti_devfreq_cdev.ko` | 恢复、Vendor |  |  |
| `qti_dynamic_hw_trip.ko` | 恢复、Vendor |  |  |
| `qti_power_telemetry.ko` | 恢复、Vendor |  |  |
| `qti_ptd_share.ko` | 恢复、Vendor |  |  |
| `qti_qmi_cdev.ko` | 恢复、Vendor |  |  |
| `qti_qmi_sensor_v2.ko` | 恢复、Vendor |  |  |
| `qti_thermal_vendor_hooks.ko` | 恢复、Vendor |  |  |
| `qti_userspace_cdev.ko` | 恢复、Vendor |  |  |
| `radio-i2c-rtc6226-qca.ko` | Vendor | 外置模块 / qcom/opensource/bt-kernel/rtc6226/Makefile |  |
| `rdbg.ko` | 恢复、Vendor |  |  |
| `rss_monitor.ko` | 恢复、Vendor |  |  |
| `rust_binder.ko` | System | 内核 / drivers/android/binder/Makefile | 生产配置待编译，本轮使用内置 C Binder |
| `sc7601.ko` | 恢复、Vendor |  | 依板级 I²C 绑定、电源拓扑和固件确认对应充电 IC |
| `sc8531.ko` | 恢复、Vendor |  | 依板级 I²C 绑定、电源拓扑和固件确认对应充电 IC |
| `sc8581.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_hardware_ic/charge_pump_ic/sc8581/Makefile | 依板级 I²C 绑定、电源拓扑和固件确认对应充电 IC |
| `sc96281_charger.ko` | 恢复、Vendor | 内核 / drivers/power/supply/mca/mca_hardware_ic/wireless_ic/sc96281/Makefile | 依板级 I²C 绑定、电源拓扑和固件确认对应充电 IC |
| `sia91xx_dlkm.ko` | Vendor |  |  |
| `sia91xx_tuning_dlkm.ko` | Vendor |  |  |
| `sla.ko` | Vendor |  |  |
| `slc_mpam.ko` | 恢复、Vendor |  |  |
| `slc_perfmon.ko` | 恢复、Vendor |  |  |
| `snd-soc-cs40l26.ko` | 恢复、Vendor |  |  |
| `snd-usb-audio-qmi.ko` | 恢复、Vendor |  |  |
| `spi_cnss_proto.ko` | Vendor | 外置模块 / qcom/opensource/bt-kernel/spi/Makefile |  |
| `spmi-pmic-arb-debug.ko` | 恢复、Vendor |  |  |
| `spmi-pmic-err-debug.ko` | 恢复、Vendor |  |  |
| `stm_nfc_i2c.ko` | Vendor |  | 已有 NXP 路径，按 NFC 控制器型号核对 |
| `stm_p_ost.ko` | 恢复、Vendor |  |  |
| `stm_st54se_gpio.ko` | Vendor |  | 依 NFC / 安全元件型号核对 |
| `stmvl53l5.ko` | 恢复、Vendor |  |  |
| `swr_dmic_dlkm.ko` | Vendor | 外置模块 / qcom/opensource/audio-kernel/asoc/codecs/Kbuild |  |
| `sys_pm_vx.ko` | 恢复、Vendor |  |  |
| `sysmon_subsystem_stats.ko` | 恢复、Vendor |  |  |
| `tango32.ko` | Vendor |  |  |
| `tas25xx_dlkm.ko` | Vendor |  |  |
| `task_attribute.ko` | 恢复、Vendor |  |  |
| `thermal_config.ko` | 恢复、Vendor |  |  |
| `ufs_ffu.ko` | 恢复、Vendor |  |  |
| `usb_f_ccid.ko` | 恢复、Vendor |  |  |
| `usb_f_cdev.ko` | 恢复、Vendor |  |  |
| `usb_f_qdss.ko` | 恢复、Vendor |  |  |
| `wcd9378_slave_dlkm.ko` | Vendor | 外置模块 / qcom/opensource/audio-kernel/asoc/codecs/wcd9378/Kbuild | Canoe 有公开构建声明，需确认板级音频拓扑 |
| `wcd937x_slave_dlkm.ko` | Vendor | 外置模块 / qcom/opensource/audio-kernel/asoc/codecs/wcd937x/Kbuild |  |
| `wcd938x_dlkm.ko` | Vendor | 外置模块 / qcom/opensource/audio-kernel/asoc/codecs/wcd938x/Kbuild |  |
| `wcd938x_slave_dlkm.ko` | Vendor | 外置模块 / qcom/opensource/audio-kernel/asoc/codecs/wcd938x/Kbuild |  |
| `wsa885x_i2c_dlkm.ko` | Vendor |  |  |
| `xiaomi_rsmc.ko` | 恢复、Vendor |  |  |

## 核对输入

原厂分区均通过完整 OTA 的 SHA-256 校验。正常启动与恢复加载清单取自 vendor_boot 平台 ramdisk，system_dlkm 目录版与扁平版同名模块计一次。

| 分区 | SHA-256 |
|---|---|
| vendor_boot | `68a80b12e8210e0683fb0f275e0df2134db591113c9d6d91acbd34f54f4409cf` |
| vendor_dlkm | `094b779c61c8b1736025230e545838001b0d4037ff2473dcbc413af128738cb4` |
| system_dlkm | `b4177b860c3c99ccacf8e1fefb8584032ba214f61fe47e9f9cd78c4d3820d0d9` |
