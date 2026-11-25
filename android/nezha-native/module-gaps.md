# 小米 17 Ultra 类原生内核适配清单

适用于国行 nezha 的 nazha 分支，底包 OS4.0.7.0.XPACNXM。以能开机、通信、拍摄、充电及正常待机为验收目标。

## 原厂模块取舍

四份原厂加载清单共有 655 个不同模块名。ARM64 4 KiB、Clang 19 的 6.12.118 构建产出 374 个树内和 87 个外置模块，其中 419 个与原厂加载项同名。下列 236 项是名称差异。一个功能可能有通用替代实现，也可能要由多个模块共同提供。

| 范围 | 名称数 | 处理方式 |
|---|---:|---|
| 卫星通信 | 4 | 退出默认构建与首启验收。保留板级接线、双卡默认路由和通用 GNSS。 |
| 原厂增强 | 28 | 暂缓独立移植，如 Millet 冻结、游戏调度和内存调优。有实际用户态或二进制依赖时再评估。 |
| 诊断测试 | 54 | 按故障开启测试、追踪或日志，不作为日用功能验收项。保留基础日志与异常采集能力。 |
| 按硬件选择 | 35 | 按本机 DT、总线 ID、probe 与 HAL 确认实际器件和配套驱动。 |
| 日用功能 | 23 | 验证对应日用功能或保护链路。标准实现经验证可替代原厂同名模块。 |
| 核对调用方 | 92 | 现有证据不足以排除。优先检查原厂硬依赖、vendor HAL/init 和实际 probe，再决定取舍。 |

## 已接入、待实机验收

| 功能 | 已核对 | 17 Ultra 实机验收 |
|---|---|---|
| ST21NFC 与 ST54 安全元件 | NFC 模块版本 2.2.0.19，依赖 SecureMSM 与 Qualcomm pinctrl。ST54 保留原厂节点名及三个复位 ioctl。 | 验证 HAL 启停、息屏唤醒、读卡和安全元件访问。 |
| SC8585 主电荷泵 | SE5 地址 0x6e、GPIO114/209 和保护阈值对应 4.0.7。主电荷泵按芯片 ID 匹配并向 MCA 注册。 | 核对 probe、接入和拔出、温度与保护状态，再测快充协商。 |
| 镜头环 | ADSP SMP2P 九路事件使用原厂设备名、输入设备 ID 和 REL_WHEEL 事件；两格和三格旋转逐格同步。 | 验证实际中断、Android 输入事件及相机对焦/变焦。 |

VL53L5/L8 测距的 SE14 CS0、三路电源、3 MHz 总线与两个固件名已接入；SE14 CS1 的卫星器件保持不启用。小米 popsicle-w-oss 参考驱动已单独试编，仍需核对固件长度、失败时电源回滚和 HAL 访问后再加入加载清单。

SC96281 正向无线充电仍待适配。原厂常规异物检测表有 32 行，2:1 表有两行；常规表有 6 行、2:1 表有 2 行的薄壳与厚壳标定不同。目前共用驱动只能表示一行 2:1 数据，且要求薄厚壳标定相同。需要接入 17 Ultra 的配件状态和对应标定，再验证在线状态及 MCA 保护链路。

## 剩余验收顺序

1. 生产配置与启动。用 Android 工具链构建 Rust Binder、检查签名和最终 vendor_boot / DLKM，在 17 Ultra 冷启动验证挂载及模块加载。
2. 蜂窝与定位。验证两张 SIM 的冷启动识别、通话、短信、数据切换与休眠恢复，单独验证普通 GNSS 定位。双卡六个路由引脚沿用原厂启动电平。MHI、QRTR、IPA、RMNET 继续按通信链路验收。
3. 电源与待机。验证 Health 电量、电流和有线/无线在线状态、USB PD、JEITA、端口过热、电池过压/过流及深度休眠。以实际功能决定需要哪些 MCA 接口。
4. 多媒体与输入。验证多摄切换、手电筒、镜头环、听筒/扬声器、麦克风、振动、显示触控、指纹、Wi-Fi、蓝牙及 NFC。

## 原厂设备树已能区分的器件

在 SG/Whale 与 Canoe 各取一份对应原厂 base + overlay，检查节点及全部父节点的 status，再核对原厂模块 alias。两组均启用 ST21NFC、ST54 GPIO、VL53L5、SC96281 与 SC8585 主电荷泵。原厂 sc8581.ko 同时匹配 sc8585_master。Canoe 参考树还启用了 Peach WLAN 和 TAS25xx。节点启用是优先适配的依据，实际装机、probe 及 HAL 验证另行完成。

## 原厂分区对照

| 加载清单 | 去重名称 | 已编出同名模块 | 差异 |
|---|---:|---:|---:|
| 启动 | 172 | 128 | 44 |
| 恢复 | 465 | 261 | 204 |
| Vendor | 404 | 213 | 191 |
| System | 82 | 81 | 1 |

原厂镜像还有 21 个只随包交付的模块名，均有同名构建产物。zram、zsmalloc 在原生布局的 vendor 侧。主机验证使用内置 C Binder。

## 逐项判断

使用 4.0.7 原厂 ELF 的 .modinfo 核对名称和 depends。下表原厂直接使用者最多展示三个，括号内为额外数量。空栏表示本批 ELF 没有声明直接依赖，用户空间打开设备节点、固件调用和 DT 供电关系仍须单独核对。

| 模块 | 原厂加载位置 | 范围 | 原厂直接使用者 | 判断依据或验证点 |
|---|---|---|---|---|
| `binder_gki.ko` | 启动、恢复 | 原厂增强 | millet_binder | 原厂 Millet 扩展；Android IPC 仍由 Binder 提供 |
| `bootinfo.ko` | 启动、恢复 | 核对调用方 |  |  |
| `boottime.ko` | 启动、恢复 | 诊断测试 | bootmonitor |  |
| `common.ko` | 启动、恢复 | 核对调用方 | gpu_freq_stats、qrtr | 原厂是 PowerInsight，QRTR 有直接依赖 |
| `cpq.ko` | 启动、恢复 | 核对调用方 |  | CPQ IO scheduler |
| `debug_ext.ko` | 启动、恢复 | 核对调用方 |  | Xiaomi Kernel Debug Extensions |
| `dio_dma_mapper.ko` | 启动、恢复 | 核对调用方 |  | A misc driver to attach to DMA-BUF and get pages to match gup requirement |
| `dynamic_readahead.ko` | 启动、恢复 | 原厂增强 |  |  |
| `et5907mv-regulator.ko` | 启动、恢复 | 卫星通信 |  |  |
| `fault_report.ko` | 启动、恢复 | 核对调用方 |  |  |
| `gpio-tiantong-dxs702.ko` | 启动、恢复 | 卫星通信 |  | Driver for tiantong GPIO control |
| `gpu_stats.ko` | 启动、恢复 | 核对调用方 | gpu_freq_stats、msm_kgsl | 原厂 KGSL 有直接依赖 |
| `hl7603-regulator.ko` | 启动、恢复 | 卫星通信 |  |  |
| `iorap2.ko` | 启动、恢复 | 原厂增强 |  |  |
| `mem_fault_events.ko` | 启动、恢复 | 核对调用方 | mi_extent_pool、mi_low_lat_mem | Memory Fault Events Coordinator |
| `mi-power.ko` | 启动、恢复 | 核对调用方 | qcom-spmi-pmic、qcom_stats | 原厂 PMIC 驱动有直接依赖 |
| `mi_damon.ko` | 启动、恢复 | 原厂增强 |  |  |
| `mi_extent_pool.ko` | 启动、恢复 | 核对调用方 | qcom_dma_heaps | 原厂 DMA heaps 有直接依赖 |
| `mi_game.ko` | 启动、恢复 | 原厂增强 |  | Frame Loading Tracking by David |
| `mi_memory.ko` | 启动、恢复 | 核对调用方 |  | Interface for xiaomi memory |
| `mi_mempool.ko` | 启动、恢复 | 原厂增强 |  | A moudle to preserve some pages for some core apps or memory allocation failures. |
| `mi_proc_exit.ko` | 启动、恢复 | 核对调用方 |  |  |
| `mi_qmi_trace.ko` | 启动、恢复 | 核对调用方 | qrtr | 原厂 QRTR 有直接依赖，混用原厂模块前需核对 |
| `mi_wq_dynamic_priority.ko` | 启动、恢复 | 原厂增强 |  |  |
| `millet_binder.ko` | 启动、恢复 | 原厂增强 |  |  |
| `millet_core.ko` | 启动、恢复 | 原厂增强 | binder_gki、millet_binder、millet_hs（另 2） | Millet smart frozen control subsystem |
| `millet_hs.ko` | 启动、恢复 | 原厂增强 |  |  |
| `millet_oem_cgroup.ko` | 启动、恢复 | 原厂增强 |  |  |
| `millet_pkg.ko` | 启动、恢复 | 原厂增强 | millet_binder |  |
| `millet_sig.ko` | 启动、恢复 | 原厂增强 |  |  |
| `mimon.ko` | 启动、恢复 | 核对调用方 |  |  |
| `mist.ko` | 启动、恢复 | 核对调用方 | bwmon、memlat、mi_game（另 1） | soc performance tuner developed by David |
| `os_cpu_qi.ko` | 启动、恢复 | 核对调用方 | cpq、mi_low_lat_mem、mi_reclaim（另 4） | MI QOS inherit Driver |
| `os_cpu_qs.ko` | 启动、恢复 | 原厂增强 |  | OS-CPU QOS sched Driver |
| `perf_actuator.ko` | 启动、恢复 | 核对调用方 | os_cpu_qi、rtg、vip_sched |  |
| `perf_helper.ko` | 启动、恢复 | 核对调用方 |  |  |
| `plat_common.ko` | 启动、恢复 | 核对调用方 | mi_game、os_cpu_qi、os_cpu_qs（另 3） | OS-CPU Platform Hook |
| `powerinsight_interface.ko` | 启动、恢复 | 核对调用方 | qca_cld3_kiwi_v2、qca_cld3_peach_v2、qca_cld3_wcn7750 | Flow tracking (IPv4/IPv6, TCP/UDP) with auto-delete on teardown/timeout |
| `rtg.ko` | 启动、恢复 | 核对调用方 | sched-walt |  |
| `scene_swappiness.ko` | 启动、恢复 | 原厂增强 |  |  |
| `swinfo.ko` | 启动、恢复 | 核对调用方 | bootmonitor、mtdoops |  |
| `unfairmem.ko` | 启动、恢复 | 原厂增强 |  | A moudle to adjust min watermark for important task. |
| `vip_sched.ko` | 启动、恢复 | 核对调用方 | mi_game、os_cpu_qi、os_cpu_qs（另 1） | MI QOS sched Driver |
| `xm_usb_pri_interface.ko` | 启动、恢复 | 核对调用方 |  |  |
| `adsp_sleepmon.ko` | 恢复、Vendor | 核对调用方 |  |  |
| `aw882xx_dlkm.ko` | Vendor | 按硬件选择 |  | ASoC AW882XX Smart PA Driver |
| `boot_stats.ko` | 恢复、Vendor | 诊断测试 |  | MSM boot stats info driver |
| `bootmonitor.ko` | 恢复、Vendor | 诊断测试 |  |  |
| `bq27z561.ko` | 恢复、Vendor | 日用功能 |  | 已有 bq27xxx 电量计路径，待验 Android Health |
| `btfm_slim_codec.ko` | Vendor | 按硬件选择 |  | BTFM Slimbus driver |
| `bwmon.ko` | 恢复、Vendor | 核对调用方 |  | QCOM BWMON driver |
| `cameralog.ko` | Vendor | 诊断测试 |  | 日志接口；需确认 HAL 可容忍设备节点缺失 |
| `cameramsger.ko` | Vendor | 核对调用方 |  | 核对相机 HAL 消息接口与多摄切换 |
| `cdsprm.ko` | 恢复、Vendor | 核对调用方 |  |  |
| `charger-ulog-glink.ko` | 恢复、Vendor | 诊断测试 |  | QTI charger ulog glink driver |
| `charger_partition.ko` | 恢复、Vendor | 核对调用方 | mca_bmd、mca_business_charger_comp、mca_smart_charge（另 2） | charger partition driver |
| `cl_dsp-core.ko` | 恢复、Vendor | 按硬件选择 | cs40l26-core、snd-soc-cs40l26 | 虽有 Debugfs 描述，实为 CS40L26 驱动的依赖 |
| `core_hang_detect.ko` | 恢复、Vendor | 诊断测试 |  | MSM Core Hang Detect Driver |
| `coresight-csr.ko` | 恢复、Vendor | 诊断测试 | coresight-dummy、coresight-remote-etm、coresight-stm（另 4） | CoreSight CSR driver |
| `coresight-qmi.ko` | 恢复、Vendor | 诊断测试 | coresight-dummy、coresight-remote-etm、coresight-tmc-sec | CoreSight QMI driver |
| `coresight-remote-etm.ko` | 恢复、Vendor | 诊断测试 |  | CoreSight Remote ETM driver |
| `coresight-tgu.ko` | 恢复、Vendor | 诊断测试 |  | CoreSight TGU driver |
| `coresight-tmc-sec.ko` | 恢复、Vendor | 诊断测试 |  | CoreSight Secure ETR driver |
| `coresight-trace-noc.ko` | 恢复、Vendor | 诊断测试 |  | Trace NOC driver |
| `coresight-uetm.ko` | 恢复、Vendor | 诊断测试 |  |  |
| `cpu_mpam.ko` | 恢复、Vendor | 核对调用方 |  | QCOM CPU MPAM driver |
| `cpucp_log.ko` | 恢复、Vendor | 诊断测试 |  |  |
| `cs40l26-core.ko` | 恢复、Vendor | 按硬件选择 | cs40l26-i2c、snd-soc-cs40l26 | CS40L26 Boosted Mono Class D Amplifier for Haptics |
| `cs40l26-i2c.ko` | 恢复、Vendor | 按硬件选择 |  | CS40L26 I2C Driver |
| `dcc_v2.ko` | 恢复、Vendor | 诊断测试 |  | MSM data capture and compare engine |
| `dmesg_dumper.ko` | 恢复、Vendor | 诊断测试 |  | QTI Virtual Machine dmesg log buffer dumper |
| `dump_binder.ko` | 恢复、Vendor | 诊断测试 |  | Xiaomi binder async buffer monitor |
| `dump_display.ko` | 恢复、Vendor | 诊断测试 |  |  |
| `f_fs_ipc_log.ko` | 恢复、Vendor | 诊断测试 |  |  |
| `ftun.ko` | Vendor | 核对调用方 |  | File Tunnel Support |
| `gh_ctrl.ko` | 恢复、Vendor | 核对调用方 | dmesg_dumper | Qualcomm Technologies, Inc. Gunyah Hypervisor Control Driver |
| `gh_panic_notifier.ko` | 恢复、Vendor | 核对调用方 | dmesg_dumper |  Qualcomm Technologies, Inc. Gunyah Panic Notifier Driver |
| `gh_rm_booster.ko` | 恢复、Vendor | 核对调用方 |  | Qualcomm Technologies, Inc. Gunyah RM booster Driver |
| `gh_tlmm_vm_mem_access.ko` | 恢复、Vendor | 核对调用方 |  | Qualcomm Technologies, Inc. TLMM VM Memory Access Driver |
| `glink_probe.ko` | 恢复、Vendor | 核对调用方 |  | Qualcomm Technologies, Inc. GLINK probe helper driver |
| `gpio-mi-t1.ko` | 恢复、Vendor | 核对调用方 |  | 外置芯片控制，按蜂窝与射频接线核实 |
| `gpu_freq_stats.ko` | 恢复、Vendor | 诊断测试 |  |  |
| `gunyah_trace.ko` | 恢复、Vendor | 诊断测试 |  | Gunyah Trace Driver |
| `hangdetect.ko` | 恢复、Vendor | 核对调用方 |  |  |
| `hardwareinfo.ko` | Vendor | 核对调用方 |  |  |
| `heap_mem_ext_v01.ko` | 恢复、Vendor | 核对调用方 | msm_memshare |  |
| `hl7603.ko` | 恢复、Vendor | 按硬件选择 |  | MCA boost/bypass 驱动，与卫星 PA 的 compatible 不同 |
| `hung_task_enh.ko` | 恢复、Vendor | 诊断测试 |  | QCOM Hung Task Enhancement |
| `hvc_gunyah.ko` | 恢复、Vendor | 核对调用方 |  | Qualcomm Technologies, Inc. Gunyah Hypervisor Console Driver |
| `hypsys_netlink.ko` | 恢复、Vendor | 核对调用方 | mi_memcheck | hypsys netlink |
| `i3c-master-msm-geni.ko` | 恢复、Vendor | 按硬件选择 |  |  |
| `icnss2.ko` | Vendor | 按硬件选择 | qca_cld3_wcn7750 | iWCN CORE platform driver |
| `io_monitor.ko` | 恢复、Vendor | 诊断测试 |  | io monitor |
| `ipclite_test.ko` | Vendor | 诊断测试 |  |  |
| `ir-spi.ko` | 恢复、Vendor | 按硬件选择 |  | SPI IR LED |
| `jtag-io.ko` | 恢复、Vendor | 诊断测试 |  | Driver for mi t2 jtag GPIO control |
| `leds-qpnp-vibrator-ldo.ko` | 恢复、Vendor | 按硬件选择 |  | QPNP Vibrator-LDO driver |
| `llcc_heuristics.ko` | 恢复、Vendor | 核对调用方 |  | QCOM HEURISTICS SCID driver |
| `lmh_stats.ko` | 恢复、Vendor | 诊断测试 |  | QCOM LMH Stats Driver |
| `lt9611uxc.ko` | 恢复、Vendor | 按硬件选择 |  |  |
| `matt.ko` | Vendor | 原厂增强 |  | XiaoMi Adaptive Tansfer Tunnel |
| `mca_basic_wireless.ko` | 恢复、Vendor | 日用功能 | mca_qcom_sysfs、mca_quick_wireless | Basic Wireless Class |
| `mca_bmd.ko` | 恢复、Vendor | 日用功能 | mca_basic_wireless、mca_business_charger_comp、mca_quick_wireless（另 4） | battery missing detection |
| `mca_buckchg_jeita.ko` | 恢复、Vendor | 日用功能 |  | buckchg jeita |
| `mca_business_battery_comp.ko` | 恢复、Vendor | 核对调用方 |  | business battery core |
| `mca_business_charger_comp.ko` | 恢复、Vendor | 核对调用方 |  | business charger core |
| `mca_business_misc_comp.ko` | 恢复、Vendor | 核对调用方 |  | business votable |
| `mca_charge_interface.ko` | 恢复、Vendor | 日用功能 | mca_basic_wireless、mca_quick_wireless、mca_strategy_buckchg（另 1） | xiaomi charge interface driver |
| `mca_charge_mievent.ko` | 恢复、Vendor | 核对调用方 | mca_basic_wireless、mca_bmd、mca_business_charger_comp（另 10） | 原厂保护和策略模块依赖此事件接口 |
| `mca_charger_thermal.ko` | 恢复、Vendor | 日用功能 | mca_qcom_sysfs | charge thermal |
| `mca_connector_antiburn.ko` | 恢复、Vendor | 日用功能 | mca_business_charger_comp | Connector antiburn |
| `mca_ibat_ocp_monitor.ko` | 恢复、Vendor | 日用功能 |  | battery ocp software protection |
| `mca_lpd_detect.ko` | 恢复、Vendor | 日用功能 | mca_business_charger_comp | usb moisture detection |
| `mca_path_control.ko` | 恢复、Vendor | 日用功能 |  | MCA Path Control |
| `mca_pd_auth.ko` | 恢复、Vendor | 核对调用方 |  | 核对标准 PD 与小米私有快充各自调用方 |
| `mca_platform_base.ko` | 恢复、Vendor | 核对调用方 |  | mca platform base |
| `mca_platform_wireless_class.ko` | 恢复、Vendor | 日用功能 | bq27z561、mca_basic_wireless、mca_bmd（另 11） | platform wireless charge class |
| `mca_qcom_smem.ko` | 恢复、Vendor | 核对调用方 | mca_charger_thermal、mca_strategy_buckchg、mca_strategy_fg_comp | mca get smem info |
| `mca_qcom_subpmic_proxy.ko` | 恢复、Vendor | 日用功能 | leds-qcom-flash、qcom-spmi-wled | qcom subpmic  driver |
| `mca_qcom_sysfs.ko` | 恢复、Vendor | 核对调用方 |  | mca qcom sysfs |
| `mca_quick_wireless.ko` | 恢复、Vendor | 核对调用方 |  | Xiaomi Wireless Quick Charge |
| `mca_smart_charge.ko` | 恢复、Vendor | 核对调用方 | mca_basic_wireless、mca_buckchg_jeita、mca_charger_thermal（另 5） | smart charge driver |
| `mca_strategy_buckchg.ko` | 恢复、Vendor | 日用功能 |  | strategy buckchg class |
| `mca_strategy_class.ko` | 恢复、Vendor | 核对调用方 | bq27z561、charger_partition、mca_basic_wireless（另 14） | mca strategy class |
| `mca_strategy_fg_class.ko` | 恢复、Vendor | 核对调用方 | mca_basic_wireless、mca_bmd、mca_buckchg_jeita（另 12） | platform fg class |
| `mca_strategy_fg_comp.ko` | 恢复、Vendor | 核对调用方 |  | Strategy Fuel Gauge Smooth |
| `mca_strategy_quickchg.ko` | 恢复、Vendor | 核对调用方 |  | strategy quick charger |
| `mca_vbat_ovp_monitor.ko` | 恢复、Vendor | 日用功能 |  | battery ovp software protection |
| `mca_wireless_revchg.ko` | 恢复、Vendor | 核对调用方 | mca_basic_wireless、mca_path_control、mca_qcom_sysfs（另 1） | 反向充电可后排，原厂正向充电也引用其符号 |
| `mem-hooks.ko` | 恢复、Vendor | 核对调用方 |  | Qualcomm Technologies, Inc. Memory Trace Hook Call-Back Registration |
| `mem-offline.ko` | 恢复、Vendor | 核对调用方 |  | Qualcomm Technologies, Inc. Memory Offlining Driver |
| `memlat.ko` | 恢复、Vendor | 核对调用方 |  | QCOM MEMLAT Driver |
| `mhi_dev_satellite.ko` | 恢复、Vendor | 核对调用方 |  | 原厂有 MHI/RPMsg 通道管理，尚无与 DXS702 绑定的证据 |
| `mhi_dev_uci.ko` | 恢复、Vendor | 核对调用方 |  | MHI 用户通道，需核对蜂窝 modem 调用方 |
| `mi_cam.ko` | Vendor | 原厂增强 |  | mi cam sched driver |
| `mi_dma_dio.ko` | 恢复、Vendor | 核对调用方 |  |  |
| `mi_low_lat_mem.ko` | 恢复、Vendor | 原厂增强 |  |  |
| `mi_memcheck.ko` | 恢复、Vendor | 诊断测试 |  | MI Memcheck Module |
| `mi_ntsync.ko` | 恢复、Vendor | 原厂增强 |  | Kernel driver for NT synchronization primitives |
| `mi_reclaim.ko` | 恢复、Vendor | 原厂增强 |  | Memory reclaim optimization module |
| `mi_stack.ko` | 恢复、Vendor | 诊断测试 |  | Register Mi Stack driver |
| `mi_thermal_interface.ko` | 恢复、Vendor | 核对调用方 |  | 核对 Thermal HAL 访问；保留限流与硬件过温处理 |
| `mi_trace.ko` | 恢复、Vendor | 诊断测试 |  | Register Mi Trace driver |
| `mi_ubt.ko` | 恢复、Vendor | 诊断测试 | mi_ubt_test | Register user backtrace driver |
| `mi_ubt_test.ko` | 恢复、Vendor | 诊断测试 |  | Register Mi Ubt Test driver |
| `mi_wmark.ko` | 恢复、Vendor | 原厂增强 |  | A moudle to adjust kswapd watermark. |
| `mibbr.ko` | Vendor | 原厂增强 |  | xiaomi kernel network extension |
| `microdump_collector.ko` | 恢复、Vendor | 诊断测试 |  | Qualcomm Technologies, Inc. Microdump Collector |
| `miicmpfilter.ko` | Vendor | 原厂增强 |  | icmp unreach module using netfilter hooks |
| `minet.ko` | Vendor | 核对调用方 |  | driver for minet |
| `miscore.ko` | Vendor | 原厂增强 |  | module for xiaomi net score |
| `mitee_dlkm.ko` | Vendor | 核对调用方 |  | MITEE TUI |
| `mpam.ko` | 恢复、Vendor | 核对调用方 | cpu_mpam、platform_mpam | QCOM MPAM driver |
| `mpam_msc.ko` | 恢复、Vendor | 核对调用方 | mpam_msc_slc、slc_mpam | QCOM MPAM MSC driver |
| `mpam_msc_slc.ko` | 恢复、Vendor | 核对调用方 |  | QCOM MPAM MSC SLC driver |
| `msm_memshare.ko` | 恢复、Vendor | 核对调用方 |  | Mem Share QMI Service Driver |
| `msm_show_epoch.ko` | 恢复、Vendor | 诊断测试 |  | Qualcomm Technologies, Inc. show epoch values driver |
| `msm_show_resume_irq.ko` | 恢复、Vendor | 诊断测试 |  | Qualcomm Technologies, Inc. MSM Show resume IRQ |
| `mtdoops.ko` | 恢复、Vendor | 诊断测试 |  |  |
| `node_cache.ko` | 恢复、Vendor | 原厂增强 |  | node cache for f2fs |
| `nuvolta_1671.ko` | 恢复、Vendor | 按硬件选择 |  | 原厂有 NU1671 异物检测参数表，参数表本身不足以证明芯片装机 |
| `pci_phy_access.ko` | 恢复、Vendor | 核对调用方 |  | Multi-RC PCIe PHY Access Driver for EOM |
| `phy-msm-snps-eusb2.ko` | 恢复、Vendor | 按硬件选择 |  | MSM USB eUSB2 PHY driver |
| `phy-qcom-emu.ko` | 恢复、Vendor | 按硬件选择 |  | 仿真用 PHY；按设备树实际匹配选择 |
| `phy-qcom-m31-eusb2.ko` | 恢复、Vendor | 按硬件选择 |  | eUSB2 Qualcomm M31 HSPHY driver |
| `pinctrl-spmi-mpp.ko` | 恢复、Vendor | 按硬件选择 |  | Qualcomm SPMI PMIC MPP pin control driver |
| `platform_mpam.ko` | 恢复、Vendor | 核对调用方 | slc_mpam | QCOM Platform MPAM driver |
| `pmic-glink-debug.ko` | 恢复、Vendor | 诊断测试 |  | PMIC Glink Debug Driver |
| `powersave.ko` | 恢复、Vendor | 核对调用方 |  |  |
| `printk_enhance.ko` | 恢复、Vendor | 诊断测试 |  | Register Printk Enhance driver |
| `qca_cld3_kiwi_v2.ko` | Vendor | 按硬件选择 |  | Canoe 参考树启用 Peach；待核对其余板型硬件 ID |
| `qca_cld3_wcn7750.ko` | Vendor | 按硬件选择 |  | Canoe 参考树启用 Peach；待核对其余板型硬件 ID |
| `qcom-amoled-regulator.ko` | 恢复、Vendor | 按硬件选择 |  | Qualcomm Technologies, Inc. AMOLED regulator driver |
| `qcom-cpufreq-hw-debug.ko` | 恢复、Vendor | 诊断测试 |  | QTI clock driver for CPUFREQ HW debug |
| `qcom-i2c-pmic.ko` | 恢复、Vendor | 核对调用方 |  |  |
| `qcom-pmic-ecid.ko` | 恢复、Vendor | 核对调用方 |  | QTI PMIC ECID driver |
| `qcom_cpuss_sleep_stats.ko` | 恢复、Vendor | 诊断测试 |  | Qualcomm Technologies, Inc. (QTI) CPUSS sleep stats driver |
| `qcom_dynamic_ramoops.ko` | 恢复、Vendor | 诊断测试 |  | Qualcomm Technologies, Inc. dynamic ramoops platform device driver support |
| `qcom_fdcvs.ko` | 恢复、Vendor | 核对调用方 |  | Qualcomm Technologies, Inc. (QTI) FDCVS driver |
| `qcom_lpm.ko` | 恢复、Vendor | 日用功能 |  | Qualcomm Technologies, Inc. cpuidle LPM governor |
| `qcom_lpm_monitor.ko` | 恢复、Vendor | 核对调用方 |  | Qualcomm Technologies, Inc. (QTI) QLPMM driver |
| `qcom_voltage_adj.ko` | 恢复、Vendor | 核对调用方 |  | Qualcomm Technologies, Inc. (QTI) QVADJ driver |
| `qmp_dlkm.ko` | Vendor | 按硬件选择 |  | ASoC QMP SDCA DMIC driver |
| `qpnp-lcdb-regulator.ko` | 恢复、Vendor | 按硬件选择 |  | QPNP LCDB regulator driver |
| `qptf.ko` | 恢复、Vendor | 诊断测试 | qti_power_telemetry、qti_ptd_share | Qcom Power Telemetry framework driver |
| `qrtr-gunyah.ko` | 恢复、Vendor | 核对调用方 |  | QTI IPC-Router Gunyah interface driver |
| `qsee_ipc_irq_bridge.ko` | 恢复、Vendor | 核对调用方 |  | QSEE IPC interrupt bridge |
| `qti-glink-adc.ko` | 恢复、Vendor | 核对调用方 |  | Glink ADC Driver |
| `qti_amoled_ecm.ko` | 恢复、Vendor | 按硬件选择 |  | QTI AMOLED ECM driver |
| `qti_battery_debug.ko` | 恢复、Vendor | 诊断测试 |  | QTI Glink battery debug driver |
| `qti_btl.ko` | 恢复、Vendor | 诊断测试 |  | QTI Battery Temperature Logging driver |
| `qti_cpufreq_cdev.ko` | 恢复、Vendor | 日用功能 |  | Qualcomm Technologies, Inc. cpufreq cooling driver |
| `qti_devfreq_cdev.ko` | 恢复、Vendor | 日用功能 |  | Qualcomm Technologies, Inc. devfreq cooling device driver |
| `qti_dynamic_hw_trip.ko` | 恢复、Vendor | 日用功能 |  | QCOM Dynamic Hardware Thermal Trip Setting Driver |
| `qti_power_telemetry.ko` | 恢复、Vendor | 诊断测试 |  | Qualcomm Technologies, Inc. Power Telemetry driver |
| `qti_ptd_share.ko` | 恢复、Vendor | 诊断测试 |  | Qualcomm Power Telemetry data share module |
| `qti_qmi_cdev.ko` | 恢复、Vendor | 日用功能 |  | QTI QMI cooling device driver |
| `qti_qmi_sensor_v2.ko` | 恢复、Vendor | 日用功能 |  |  |
| `qti_thermal_vendor_hooks.ko` | 恢复、Vendor | 核对调用方 |  | QCOM Thermal Vendor Hooks Driver |
| `qti_userspace_cdev.ko` | 恢复、Vendor | 核对调用方 |  | Userspace cooling device driver |
| `radio-i2c-rtc6226-qca.ko` | Vendor | 按硬件选择 |  | I2C radio driver for rtc6226 FM Tuner |
| `rdbg.ko` | 恢复、Vendor | 诊断测试 |  | rdbg module |
| `rss_monitor.ko` | 恢复、Vendor | 诊断测试 |  | Per-process RSS memory change tracking via tracepoints |
| `rust_binder.ko` | System | 日用功能 |  | 主机使用内置 C Binder，生产 Rust 配置待编译 |
| `sc7601.ko` | 恢复、Vendor | 按硬件选择 |  | SC sc7601 Driver |
| `sc8531.ko` | 恢复、Vendor | 按硬件选择 |  | SC sc8531 Charge Pump Driver |
| `sc96281_charger.ko` | 恢复、Vendor | 日用功能 |  | 两组原厂板型启用 sc,sc96281-wireless-charger，需验正向无线充电 |
| `sia91xx_dlkm.ko` | Vendor | 按硬件选择 |  | SI-IN SIA81xx ASoC driver |
| `sia91xx_tuning_dlkm.ko` | Vendor | 按硬件选择 |  |  |
| `sla.ko` | Vendor | 核对调用方 |  |  |
| `slc_mpam.ko` | 恢复、Vendor | 核对调用方 |  | QCOM SLC MPAM driver |
| `slc_perfmon.ko` | 恢复、Vendor | 诊断测试 |  | QCOM SLC PERFMON |
| `snd-soc-cs40l26.ko` | 恢复、Vendor | 按硬件选择 |  | ASoC CS40L26 driver |
| `snd-usb-audio-qmi.ko` | 恢复、Vendor | 核对调用方 |  | USB AUDIO QMI Service Driver |
| `spi_cnss_proto.ko` | Vendor | 核对调用方 |  | spi cnss driver |
| `spmi-pmic-arb-debug.ko` | 恢复、Vendor | 诊断测试 |  |  |
| `spmi-pmic-err-debug.ko` | 恢复、Vendor | 诊断测试 |  | QCOM SPMI error debug driver |
| `stm_p_ost.ko` | 恢复、Vendor | 诊断测试 |  | MIPI Open System Trace STM framing protocol driver |
| `stmvl53l5.ko` | 恢复、Vendor | 日用功能 |  | 两组均有启用的 st,stmvl53l5 测距节点，需结合相机 HAL 验证 |
| `swr_dmic_dlkm.ko` | Vendor | 按硬件选择 |  | SWR DMIC driver |
| `sys_pm_vx.ko` | 恢复、Vendor | 诊断测试 |  | Qualcomm Technologies, Inc. (QTI) System PM Violators driver |
| `sysmon_subsystem_stats.ko` | 恢复、Vendor | 诊断测试 |  | Qualcomm Technologies, Inc. Sysmon subsystem Stats driver |
| `tango32.ko` | Vendor | 原厂增强 |  | 32-bit syscall support for the Tango binary translator |
| `tas25xx_dlkm.ko` | Vendor | 按硬件选择 |  | Canoe 参考树启用 ti,tas25xx，按板型验证功放 |
| `task_attribute.ko` | 恢复、Vendor | 原厂增强 |  | MIUI Task Attribute Scheduler Module - Cluster Packing Optimizer |
| `thermal_config.ko` | 恢复、Vendor | 核对调用方 |  | 描述为热区配置调试接口；核对 thermal HAL 是否写入 |
| `ufs_ffu.ko` | 恢复、Vendor | 核对调用方 |  | Interface for xiaomi memory |
| `usb_f_ccid.ko` | 恢复、Vendor | 核对调用方 |  | USB CCID function Driver |
| `usb_f_cdev.ko` | 恢复、Vendor | 核对调用方 |  | USB Serial Character Driver |
| `usb_f_qdss.ko` | 恢复、Vendor | 诊断测试 | coresight-tmc | USB QDSS Function Driver |
| `wcd9378_slave_dlkm.ko` | Vendor | 按硬件选择 |  | WCD9378 Swr Slave driver |
| `wcd937x_slave_dlkm.ko` | Vendor | 按硬件选择 |  | WCD937X Swr Slave driver |
| `wcd938x_dlkm.ko` | Vendor | 按硬件选择 |  | WCD938X Codec driver |
| `wcd938x_slave_dlkm.ko` | Vendor | 按硬件选择 |  | WCD938X Swr Slave driver |
| `wsa885x_i2c_dlkm.ko` | Vendor | 按硬件选择 |  | Qualcomm Technologies, Inc |
| `xiaomi_rsmc.ko` | 恢复、Vendor | 卫星通信 |  | X801 SPI 通道，共用卫星 PA 电源；保留普通 GNSS 验收 |

## 核对输入

原厂分区均通过完整 OTA 的 SHA-256 校验。正常启动与恢复加载清单取自 vendor_boot 平台 ramdisk，system_dlkm 目录版与扁平版同名模块计一次。

| 分区 | SHA-256 |
|---|---|
| vendor_boot | `68a80b12e8210e0683fb0f275e0df2134db591113c9d6d91acbd34f54f4409cf` |
| vendor_dlkm | `094b779c61c8b1736025230e545838001b0d4037ff2473dcbc413af128738cb4` |
| system_dlkm | `b4177b860c3c99ccacf8e1fefb8584032ba214f61fe47e9f9cd78c4d3820d0d9` |
