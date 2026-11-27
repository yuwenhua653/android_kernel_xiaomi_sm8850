# 小米 17 Ultra 类原生内核适配清单

适用于国行 nezha 的 nazha 分支，底包 OS4.0.7.0.XPACNXM。以能开机、通信、拍摄、充电及正常待机为验收目标。

## 2026-11-27：选择性吸收外部补丁并修正反例

本轮基于 `ef7a1dc`，审查附件 `17U.zip` 的 5 个内核补丁和 2 个 DT 补丁后，选择性吸收以下部分：

- **charge_interface 接入**：配置和 vendor_dlkm/recovery 清单启用 `mca_charge_interface.ko`，DT 新增 `mca,charge_interface`。Nezha 输入挂起成功后发送共享 OSS `MCA_EVENT_BATTERY_STS_CHANGE=0x11`，不再发送被 OSS 解释为健康变化的原厂 `0x13`。真实 business_battery 消费者函数已串联主机测试；Myron 原有局部事件映射保持。
- **温控表格式**：增加显式 `xiaomi,wireless-thermal-columns=<10|11>`；未提供时保留旧 10 列。拒绝畸形字段、非法列数、表长和读取失败。110 项数据按默认/显式 10 列解析为 11 行，显式 11 列才解析为 10 行，不再猜格式。
- **温控参数落地**：附件中的 150 个有线值、165 个无线值逐项等于 MiCode `kernel_devicetree@396596c6d1ec3c349402c50913f781efbf343d9c` 的 Nezha 表。写入现有 `qcom/nezha-charger-common.dtsi`，明确 11 列，温控节点保持 disabled。未复制未独立核验的 JEITA、电压、GPIO/PMIC 或保护整套节点；此比较不是本轮重新解包 OTA 的证明。
- **日志回调清理**：采用注册/读取互斥；NULL 注销等待当前回调结束。修复 NULL 函数判断、负 slot 越界、负长度/超大 snprintf 返回值和换行长度处理。该修复不代表其他策略/voter 生命周期已完成。

验证：`test-mca-charge-interface.py`（通用/Nezha，真实消费者函数）、`test-nezha-thermal-format.py`、`test-mca-log-lifetime.py` 均通过 ASan/UBSan 主机测试。注册器和 OF/API 使用桩，不是内核运行验证。加载项/Makefile 选择另做核对；没有本轮 ARM64 全量编译、最终 DTB 合并或实机充电通过记录。

**剩余 P0**：voter 所有权/同步退出、smart-charge 全局指针和文件生命周期、完整 JEITA/温控/保护执行端、无线接收器及快充。`charge_interface` 在没有策略提供者时仍返回错误，不会因本轮启用就提供快充。第 11 列 `xiaomi_car` 只保留/解析，尚无对应保护 voter，现有 10 路 voter 循环不访问新增空槽；不启用无线温控来掩盖该缺口。相机本轮未修改。

## 2026-11-27：电池读数接入与相机命令修复

- 新增标准目录下 `mca_nezha_fg_psy`，通过 DT `power-supplies` phandle 连接现有 BQ27Z561；供应者未注册时延迟 probe。配置和 vendor_dlkm 清单已接入，三个新增加载项仅为两层注册器和只读桥接。
- 提供 SOC、温度、电压、电流、循环数、容量、健康及充满状态。uV 转 MCA mV；BQ 正充电电流转换为 MCA 负充电，仍保持 uA；温度 deci-C、容量 uAh 不缩放。读取失败保留调用者输出，未提供的认证、FFC/快充控制等返回不支持。
- FG 注册层补 SRCU/拒绝重复注册/同步注销，新的桥接通过 devres 先等待回调退出，再释放 power_supply 引用和私有数据。历史完整 FG 策略驱动仍需自己接入注销；本轮未启用该驱动。
- 相机按官方 songyuan 的 8 字节闪光灯电流查询布局增加 Nezha 解析，保留通用 12 字节布局；只按描述符声明长度访问，错误不伪造电流值。
- OIS V2 固件参数表先验长度再读字段；修复零除数、尾包越界、未对齐 word 读取、偏移减法下溢和写失败被忽略。版本检查 I/O 失败不继续下载；已解析过版本设置时仍正确跳过对应字节。

验证：7 个内核主机测试脚本及相机命令脚本通过，相机分别覆盖通用/Nezha 配置。实际 C 函数在 ASan/UBSan 与 I/O/SRCU/devres 桩下测试，**未完成本修订的 ARM64 全量编译、最终 DTB/DLKM/镜像或实机验收**。

仍缺：完整充电策略、JEITA/温控/保护执行端及事件转换；无线接收器接入；OIS 64 字节名称/扩展 opcode ABI、SEM1218S OIS 固件协议、OIS/actuator 私有停驻和动态供电，以及 HAL 开流/重开/多摄切换实测。已接入的 SEM1218S zoom 不等于 OIS 协议也已完成。社区相机应用/用户态兼容工作不作为内核驱动完成证据。

## 2026-11-27：审查外部有线补丁后的修复

- 新增独立 `XIAOMI_MCA_STRATEGY_CLASS`，默认沿用 Myron SERVICES；只拆通用注册层，不启用尚未接通的充电策略。OVP/OCP 原有 SERVICES 选择条件保持，避免 COMPLETE 未开启时丢失旧模块。
- Nezha business USB 借用现有供应者，未出现时返回 EPROBE_DEFER 并传到 probe；不改借用对象的描述符/回调、不注销其设备。引用通过 devres 释放；自建供应者由 devres action 配对注销，避免重复注销。
- 策略分发增加 SRCU 读保护、重复注册拒绝、错误传播及按 data 身份同步注销接口。现有所有策略尚未全部改为调用注销；不能据此宣布生命周期收敛。
- OVP/OCP 采样错误不使用未初始化数据、不作为清除故障事件发布；USB 已在线时无需无线提供者。状态从函数 static 移到设备实例。补 sysfs/延迟任务的失败清理、remove/shutdown 清理；监测阈值未提高。
- OVP 按已有单 FG 1S/2S 枚举区分支持范围；IBAT 仍只支持并联拓扑，单 FG 不宣称已经提供 OCP。温度门限/快充条件等现有策略仍需与原厂参数及执行端核对。
- FG → business → Nezha JEITA 使用共享 OSS DTPT 枚举，纠正混入原厂 0x37 的问题；FG 读取失败不撤销已有 DTPT 状态。实际三段函数通过同步桩串联测试；真实通知队列/保护执行仍未验收。

验证：6 个源码级主机测试脚本（USB 两种产品路径、策略注册/注销并发模型、OVP/OCP 故障路径、DTPT 路由、JEITA 事件、Makefile 组合）通过；C 测试使用 ASan/UBSan，显式资源断言，未声称通过 LeakSanitizer 或内核 SRCU 测试。**本次未重新完成完整 ARM64 内核/modpost 构建；此前 463 模块结果不覆盖这些新改动。**

原补丁的 `WIRED_STRATEGY=m` 和新增加载项没有直接启用。仍需：FG 硬件提供者、smart-charge/诊断依赖解耦、完整策略注销、DT 参数及保护执行链、原厂事件边界映射、最终构建与实机验证。USB business 模块也仍受原构建门控，本轮不声称已运行。

详细说明与命令见 `wired-strategy-review.md`。

## 当前优先级：六项基础功能（2026-11-26）

本轮按最终合并设备树、构建入口和加载清单重新核对。此前的 461 个模块构建记录是历史主机结果，不是本轮重编或 17 Ultra 实测。源码能编译、DT 能合并和实机功能正常分别验收。

| 功能 | 本轮确认的状态 | 未完成事项 |
|---|---|---|
| 有线充电 | **本轮接入 Nezha sub-PMIC 基础提供者**：USB 在线/电压/电流、BC1.2 类型、buck 限流/限压/启停回调；按 4.0.7 命令编号实现，并加入配置、DT 和加载清单。GLINK 订阅增加同步注销。 | **P0**：charge interface 实现已加固，但与 Nezha JEITA/温控、策略及保护链路的接通尚未完成。此提供者不在 probe 写入充电参数，不代表快充完成；后续接口必须复用已有 `usb` power_supply，避免重名注册。 |
| 无线充电 | SC96281 已支持实际 32+2 行、普通/薄壳/厚壳 FOD，以及双 Hall 映射；表格与失败路径主机测试通过。 | **P0**：接收器 DT/加载入口与 MCA 控制/保护链路尚未接通；这是 17 Ultra 的适配缺口，不引用 Myron 的掉电现象作为本机实测。 |
| 触摸 | `xiaomi_touch.ko`、`synaptics_tcm2.ko` 有构建和加载入口，SPI SE19 节点与父总线启用。固件按 DDIC 选择。 | OS4 固件/THP 文件、上电下载、正常输入、息屏唤醒与恢复模式触摸需在本机验收。尚无证据可标记运行正常。 |
| 相机 | Canoe 四路 sensor、供电/CCI/I²C/闪光灯节点及 `v2.4.0-1` 默认表已接入。**本轮移植官方 `qcom,zoom` / SEM1218S、组件注册、请求接口和 `zoom-src` 查询；按原厂证据补齐 Nezha 44 字节能力查询，保留通用 40 字节 ABI。** 固件错误路径和共享时钟错误码修复，整个 `camera.o` 编译链接及 200 个 I²C 故障注入通过。 | **已补 CSI AutoEQ/备用 EQ、CRC 阈值和按当前错误事件触发的恢复，实际编译表与 4.0.7 一致。P0**：0x1005 动态 CSID 错误分类已实现；其余 HAL 私有 ABI/OIS/actuator 行为仍需核对；长焦运动、固件、开流、重开、多摄切换、闪光灯及前后摄均未实机验证。不能把驱动已接入标为相机已可用。 |
| 基带 | Modem PAS、SMP2P/GLINK、QRTR、IPA/RMNET 有源码/配置或加载入口，原生 modem 节点启用；保留双卡默认路由。 | 验证固件启动、RIL/IMS、两张 SIM、通话/短信/数据和休眠恢复。现阶段没有基础模块整体缺席的证据，也没有实机通过记录。 |
| Wi-Fi | **已补 Canoe 板级遗漏**：Peach CNSS、PCIe 电源域、WLAN 内存/IOMMU、复位/唤醒引脚、供电和 XO 校准单元。CNSS 与 Peach WLAN 模块已有构建/加载入口。 | 固件/板级校准文件、PCIe 枚举、扫描连接、热点与休眠恢复待实测。原厂 SG/Whale 小型入口也没有这组节点；本次以原厂 Canoe 整机入口为范围，不扩展其它板型。 |
| 蓝牙 | **已补 Canoe 板级遗漏**：原厂电源节点、共享复位、PMIC pinctrl/NVMEM 及 SE18 UART；`btpower`、`btfmcodec`、`bt_fm_swr` 已列入构建/加载。 | HCI 固件、HAL/串口初始化、配对/重连及通话音频待实测；SoundWire 板级音频链路本轮已接入，实际音频传输仍待验证。原厂 `bt_uwb_en` 是蓝牙也使用的共享复位状态，暂缓 UWB 不等于删除它。 |

当前修补顺序为充电控制/保护、相机 CSI 与板级配置，然后按本机日志收敛触摸与通信问题。卫星、UWB、NFC、镜头环增强、游戏调度和厂商诊断的独立补全后排；若证明它们是基础功能的硬依赖，再提升优先级。

### 本轮主机证据与边界

- 从同一 4.0.7 OTA 恢复并核对 `dtbo` 和 `vendor_boot`，SHA-256 分别为 `1b78a4cc5fe5ee46fcf1ea3af0ee5a1287c0b4a2ef78a30f4b62f745d31505ac`、`68a80b12e8210e0683fb0f275e0df2134db591113c9d6d91acbd34f54f4409cf`。验证了所取分区及操作数据哈希，不声称本次重验整个 OTA 签名。
- 12 个原生 base 与对应板级入口完成主机编译/合并；本次连接功能修补只接入六个已使用 Canoe 完整入口的 base：canoe、canoe-v2、canoe-tp、canoe-tp-v2、canoep、canoep-v2。
- 六个 Canoe 合并结果分别核对 194 项原厂连接功能属性，含 phandle 指向；不是通过替换数字地址消除错误。Canoe 原厂完整合并树也确认两个蓝牙电源节点均存在且未禁用。
- 新增设备树仓库 `tools/check-nezha-basics.py`，对最终 DTB 检查基础节点及所有祖先的启用状态，拒绝用未合并 DTBO 充当验收结果。它只检查节点存在性，不证明驱动绑定、供电值、固件、HAL 或硬件正常。六个 Canoe 最终树现已具有基础相机节点；仍应报告 charge interface 和无线接收器缺失。节点检查不覆盖相机驱动/HAL 的剩余缺口。

### 本轮补充验证：sub-PMIC 与相机

- ARM64 / Clang 19：当前 Nezha 配置下 MCA 子树、修改的 CSI PHY 和相机资源管理对象编译通过；新 sub-PMIC 复合对象链接通过。当前主机验证使用 C Binder；后续本轮已完成 vmlinux/Image、375 个树内与 88 个外置模块及 modpost。Android Rust Binder 生产配置、签名与可刷镜像仍未验证。
- 正常 Kbuild 入口 `vendor/qcom/nezha-canoe-board-overlay.dtbo` 编译通过；DTC 仍有原厂风格节点/overlay 上下文警告，不称为无警告。
- 六个 Canoe 最终合并树各通过 648 项原厂相机属性/引用核对，以及共享 GPIO 的一项等价转换检查；Wi-Fi/蓝牙的 194 项属性回归检查通过。共享引脚不再依赖原厂固定基址 512。
- `tools/verify-nezha-csiphy.py` 对实际 ARM64 编译对象和原厂 `camera.ko` 校验：29 档默认速率、全部 PHY/variant 指针、9 组寄存器表（含备用 EQ）、lane offsets 一致。该工具不验证 OEM AutoEQ 重试、HAL 或实机出图。
- 本轮额外核对 `vendor_dlkm` SHA-256：`094b779c61c8b1736025230e545838001b0d4037ff2473dcbc413af128738cb4`；其中 `camera.ko` SHA-256：`9c5f719297511f0e54c03dbe225acd1d179c2b83deb5fff8997dd5b7e2d39774`。原厂二进制仅作比对材料，不随 Git 提交。

## 本轮补全：CSI、音频和振动（2026-11-26）

- 相机：实现 UMD 0x1000–0x1004，加入并发保护、参数范围检查、每次配置固定一次 EQ 选择及按当前 CRC 事件的完整恢复。保留 4.0.7 的 12 项备用寄存器设置，没有引入新版额外的 0x108c 写入。0x1005 现已实现，拒绝空/重叠/未知掩码，保留未指定错误的默认分类及已有 IRQ 订阅。
- 音频 DT：新增标准板级 include `qcom/nezha-canoe-audio.dtsi`，补齐 WCD939x、LPASS、TAS25xx I²C 接线、蓝牙 SoundWire、SDAM、PMIH010x 振动和波形。无需构建时重新提取底包。
- 振动驱动：读取 Nezha 自定义波形 8500 mV、校准 2100 mV、F0 160–180 Hz / 默认 170 Hz / 计数 570；普通波形维持 2000 mV，保留硬件限压与既有除零保护。其他产品沿用原有默认值。小米动态 sysfs、强制关闭自谐振和诊断寄存器转储不在本轮范围内。
- 验证：整个 ARM64 `camera.o` 与 `qcom-hv-haptics.o` 编译通过；音频 machine、WCD939x codec/slave、BT SoundWire、SWR haptics、LPI pinctrl 六个复合对象编译链接通过。后续本轮已补完整 `.ko` modpost 和 CRC 检查；签名与镜像验收仍未完成。
- 六个 Canoe 最终合并 DTB 各通过 1294 项原厂音频/振动属性及引用检查；相机 649 项（含 GPIO 等价转换）和连接功能 194 项回归通过。工具：设备树仓库 `tools/verify-nezha-audio.py`。
- CSI 实际源码主机测试通过 ASan/UBSan：解析/范围、备选优先级、越界 PHY、重试回绕、八路并发各 10000 次与失败清理。振动实际解析/回退代码通过正常值、边界及缺失参数测试。LeakSanitizer 受主机 tracer 限制，采用显式分配计数，不声称通过 LSan。

## 本轮补全：功放、FOD 与充电接口（2026-11-26）

- **TAS25xx**：移植 Google 托管的 TI GPL 驱动，接入 Nezha Kbuild 和 vendor_dlkm 加载清单；双通道独立 I²C client、接收器 GPIO 控件、Primary TDM RX/TX 接线均已补入。原厂 machine 模块确认两条链路都使用 `tas25xx ASI1`，使用 OF 引用替代固定 Linux 总线号。
- 调音文件来自原厂 ODM，12631 字节，SHA-256 `03ad1ce1e80b7ba9287d32711f245648280c4592c384f95b6174e7873e008680`。只核对已提取操作的哈希，不声称校验整个 ODM 分区。实际格式包括空 DFREG 扩展，头部参考板地址不覆盖板级 DT。二进制不随源码上传。
- 固件预检通过实际文件、全部截断位置与 20000 次变异输入；实际解析器通过 4 个 profile、16 个控件、每通道 19 个中断及全部 92 个分配失败点测试，显式确认零遗留分配。另测 profile 越界及声卡引用/失败清理。未启用工厂 misc/debug 传输或旧 AFE 算法后端。
- **SC96281**：已支持全部普通与 2:1 UUID、三组标定、普通回退和 Hall 优先级；选择与 Hall 更新串行，写入失败不会伪装成功。仍未为 Nezha 启用无线策略、DT 和加载清单；这一步不能称为无线充电已完成。
- **charge interface**：Nezha 通知事件 0x13；缺失提供者/回调返回错误，广播保留真实失败；增加 SRCU 同步注销。主机测试覆盖上述行为及注销等待，但不替代内核 SRCU 验证。接口尚未绑定 Nezha 充电策略。

**未完成的源码/集成项**：有线 JEITA、温控/端口保护、MCA 策略/事件编号统一核对；SC96281 与无线策略接通；相机其余私有协议核对。没有通过修改状态文本把这些算作完成。songyuan 的 MCA 仍是外部 vendor 符号链接，未提供完整实现。

**未完成的验收项**：生产 Android Rust Binder/工具链、最终 DLKM/镜像/签名及 17 Ultra 实机回归。完整主机外置模块 modpost 与 CRC 已通过。音频主机测试不能证明扬声器保护、音量、通话或待机正常；触摸、基带、Wi-Fi、蓝牙也保持待实测。

## 本轮全量主机验收与 JEITA 加固（2026-11-26）

- 6.12.118、ARM64、Clang 19、C Binder 主机配置：`vmlinux`、`Image`、375 个树内模块以及 BoardConfig 顺序下的 32 个外置目录、88 个外置模块全部编译及 modpost 通过。没有放宽未定义符号检查。
- 对 463 个实际 `.ko` 检查架构、统一 vermagic、依赖存在性及 26739 项导入 CRC；六份模块清单无非预期缺件。显式例外仅 `rust_binder.ko`（主机使用内置 C Binder）。工具 `tools/check-nezha-built-modules.py` 默认不豁免，必须显式传 `--host-c-binder`。这不检查最终镜像、签名、加载时序或硬件。
- JEITA 分别跟踪有线/无线在线状态，断开一路时保留另一路的温度监控；只在最终断开时停止。此前直接采用原厂 DTPT 0x37；2026-11-27 已改为共享 OSS 事件枚举，与 FG 和业务转发一致。原厂原始事件 ABI 仍需在边界单独转换。
- JEITA 普通/FFC/电压子表使用设备托管分配；缺失、空表、损坏、范围/顺序错误及分配失败会终止 probe。可选 FFC 仅在真正缺失时跳过，子表错误不再被后续成功覆盖；OF 引用在所有退出路径释放。去掉硬编码重试 49 次及解析失败仍注册策略的路径。
- 实际解析源码通过 ASan/UBSan，包含官方 Nezha 国内、第二组电池和全球参数：共 26 个分配失败点、538 个字符串读取失败点，以及各字段损坏和表长异常。该测试不代表已选用第二组电池或接通所有温控策略。
- **仍阻塞充电启用**：策略与 smart-charge 回调生命周期、完整事件编号及消费者、JEITA/温控/端口保护接通。例：原厂 Hall 事件为 0x48，而当前共享头文件把 0x48 分给 FCC_TOO_LOW；不可只换一端常量或混用原厂模块。无线接收器仍未启用。相机私有协议及音频保护/HAL 行为仍需设备证据。

验证汇总：`host-validation-20261126.json`。该记录仅对应主机构建，不是可刷包或生产验收报告。

## 原厂模块取舍

以下名称统计是此前构建快照，不是当前未完成数量。本轮实际重编为 375 个树内加 88 个外置模块（463 个），新增 sub-PMIC 与 TAS25xx；历史差异表仅用于追踪原厂模块取舍。四份原厂加载清单共有 655 个不同模块名。ARM64 4 KiB、Clang 19 的 6.12.118 构建产出 374 个树内和 87 个外置模块，其中 419 个与原厂加载项同名。下列 236 项是名称差异。一个功能可能有通用替代实现，也可能要由多个模块共同提供。

| 范围 | 名称数 | 处理方式 |
|---|---:|---|
| 卫星通信 | 4 | 退出默认构建与首启验收。保留板级接线、双卡默认路由和通用 GNSS。 |
| 原厂增强 | 28 | 暂缓独立移植，如 Millet 冻结、游戏调度和内存调优。有实际用户态或二进制依赖时再评估。 |
| 诊断测试 | 54 | 按故障开启测试、追踪或日志，不作为日用功能验收项。保留基础日志与异常采集能力。 |
| 按硬件选择 | 36 | 按本机 DT、总线 ID、probe 与 HAL 确认实际器件和配套驱动。 |
| 日用功能 | 23 | 验证对应日用功能或保护链路。标准实现经验证可替代原厂同名模块。 |
| 核对调用方 | 91 | 现有证据不足以排除。优先检查原厂硬依赖、vendor HAL/init 和实际 probe，再决定取舍。 |

## 已接入、待实机验收

| 功能 | 已核对 | 17 Ultra 实机验收 |
|---|---|---|
| ST21NFC 与 ST54 安全元件 | NFC 模块版本 2.2.0.19，依赖 SecureMSM 与 Qualcomm pinctrl。ST54 保留原厂节点名及三个复位 ioctl。 | 验证 HAL 启停、息屏唤醒、读卡和安全元件访问。 |
| SC8585 主电荷泵 | SE5 地址 0x6e、GPIO114/209 和保护阈值对应 4.0.7。主电荷泵按芯片 ID 匹配并向 MCA 注册。 | 核对 probe、接入和拔出、温度与保护状态，再测快充协商。 |
| 镜头环 | ADSP SMP2P 九路事件使用原厂设备名、输入设备 ID 和 REL_WHEEL 事件；两格和三格旋转逐格同步。 | 验证实际中断、Android 输入事件及相机对焦/变焦。 |

VL53L5/L8 测距的 SE14 CS0、三路电源、3 MHz 总线与两个固件名已接入；SE14 CS1 的卫星器件保持不启用。小米 popsicle-w-oss 参考驱动已单独试编，仍需核对固件长度、失败时电源回滚和 HAL 访问后再加入加载清单。

SC96281 的 32 行普通、两行 2:1 表以及薄厚壳差异现已能完整表示并通过原厂表测试。
正向无线接收器和 MCA 保护策略的集成尚未完成；不把 FOD 解析完成等同于实际充电可用。

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
| `mca_qcom_subpmic_proxy.ko` | 恢复、Vendor | 日用功能 | leds-qcom-flash、qcom-spmi-wled | 已接入 Nezha 基础提供者；原厂完整策略/OTG/保护尚未完成 |
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
| `spi_cnss_proto.ko` | Vendor | 按硬件选择 |  | 源码说明为 UWB SPI 协议；本轮后排，不当作基础蓝牙 HCI 缺失模块。共享电源/复位另行保留。 |
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

## 官方 songyuan-w-oss 对照补全（2026-11-26）

本轮相机模块实现与验证详见模块仓库 `qcom/opensource/camera-kernel/NEZHA-PORT.md`。
内核 manifest 已固定本轮模块及设备树提交；设备树本轮补入 OS4.0.7 音频与振动接线。

| 官方来源 | 已确认的用途 | 当前边界 |
|---|---|---|
| `MiCode/vendor_qcom_opensource_camera-kernel@798f548761f381b056f2e1fe615f9db930aa5c7e` | Nezha zoom 驱动、93 字节配置 ABI、44 字节传感器查询；已移植并做主机验证。 | AutoEQ、CRC 阈值、恢复及 0x1005 动态分类已接入；其他私有相机接口与实测仍待完成。 |
| `MiCode/vendor_qcom_proprietary_camera-devicetree@f82a3debe8ed8dc2529d90473d73ab9a49d8aa13` | Nezha 长焦 zoom 接线与已有原厂还原节点相符。 | 不用更新整份板级树来覆盖已核对的 4.0.7 配置。 |
| `MiCode/kernel_devicetree@396596c6d1ec3c349402c50913f781efbf343d9c` | Nezha JEITA、SC96281、磁吸薄厚壳 FOD 等公开配置，可继续核对国内底包。 | 配置公开不等于 MCA 策略/无线接收器驱动已完成；保持有线/无线 P0。 |
| `MiCode/Xiaomi_Kernel_OpenSource@da9af1b6d83e1f53e4b8e4f4421e3c4161d2133d` | 包含 Nezha 目标、模块清单及振动参数处理；本轮择取自定义/校准电压和 F0 回退。 | MCA 是外部 vendor 路径符号链接，且部分 Nezha build 配置不在这次发布内；不能把该链接当作完整驱动源码。 |

卫星、UWB、厂商诊断仍后排。触摸、基带、Wi-Fi、蓝牙本轮未据此新增完成标记。

## 核对输入

原厂分区均通过完整 OTA 的 SHA-256 校验。正常启动与恢复加载清单取自 vendor_boot 平台 ramdisk，system_dlkm 目录版与扁平版同名模块计一次。

| 分区 | SHA-256 |
|---|---|
| vendor_boot | `68a80b12e8210e0683fb0f275e0df2134db591113c9d6d91acbd34f54f4409cf` |
| vendor_dlkm | `094b779c61c8b1736025230e545838001b0d4037ff2473dcbc413af128738cb4` |
| system_dlkm | `b4177b860c3c99ccacf8e1fefb8584032ba214f61fe47e9f9cd78c4d3820d0d9` |
