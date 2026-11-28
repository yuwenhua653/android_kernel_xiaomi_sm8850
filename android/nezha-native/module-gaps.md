# 小米 17 Ultra 类原生内核适配清单

适用于国行 nezha 的 nazha 分支，底包 OS4.0.7.0.XPACNXM。以能开机、通信、拍摄、充电及正常待机为验收目标。



## 2026-11-28：无线生命周期、反向充电和相机协议合并修复（当前状态）

接续内核 `e21e7372fd37` / 模块 `e1864d663b34`；本节优先于以下历史清单。此前四类有线源码修复保留，本批集中处理另外三条无线策略及相机 OIS/执行器入口，没有把单个修复当作整个适配完成。

| 范围 | 本批完成的源码工作 |
| --- | --- |
| basic wireless | 拆分 IRQ/TX 链表，保留 bit31 IRQ；改为有限任务排空，避免长期占用 system workqueue。7 个全局接口用 SRCU 保护；15 个 owned voter；检查注册失败并按所有权反向释放，停止 20 个任务、清队列/表/电池引用。初始在线查询等待 voter 就绪，失败重试。 |
| quick wireless | 4 个 owned voter、注册回滚和 remove/shutdown。事件/monitor/状态入口串行；数据锁内不再同步等待 worker，保护回调争用时延后处理。主/从 CP、UCP、ADC、parallel 和 FG 独立停用，首错保留、stop_pending 重试、确认后才清活动状态。电流限制接入实际选择，调试值也受限制；表替换失败保留原数据，阶段和数组访问有边界。计数器改为实例字段。 |
| reverse wireless | 全局接口 SRCU、16 个任务和事件入口串行；注销等待读者和任务。boost 各步检查并回滚，记录实际尝试的电源路径；TX 和笔充类型设置失败同样回退。所有已尝试电源独立关闭，首错保留，失败重试并阻止再次启充；成功后才清硬件活动账目。固件更新专用 PMIC 路由单独追踪，关机不重新打开共享 OVP。 |
| OIS / actuator | Nezha 64 字节名称、29 字节扩展 opcode / 101 字节 slave-info ABI；SEM1218S 48 KiB 固件协议及分包/CRC/版本错误处理。8 字节执行器电压命令完整预检与回滚；OEM OIS/执行器归位命令、任务提交失败清理、归位错误后的断电尝试和 shutdown 等待。详见模块树 `camera-kernel/NEZHA-PORT.md`。 |

**验证与交付范围**：本地 Clang/LLVM/LLD 19.1.7 下完整 `Image + modules` 已通过严格 modpost；本地临时启用完整 MCA 以使所有相关对象参与构建，WERROR/CFI/MODVERSIONS/GENDWARFKSYMS 开启。Rust、BTF、自动模块签名因验证环境而关闭；这些只在输出目录配置中，未修改生产 defconfig。主机回归和相机最终链接结果、确切命令/哈希见 `mca-wireless-camera-validation-20261128.json`。这比此前仅四个对象/组合对象检查覆盖更广，仍不是生产工具链/签名/最终分区或实机验收。

**明确保留的边界**：

- 完整 MCA 的原厂 GLINK 所有权、事件/保护执行端、SC96281 FOD/保护联动和整机充电状态仍需端到端集成核验；生产配置继续关闭完整 MCA。basic 策略的全部状态字段并未统一由一个 mutex 覆盖，主机锁测试也不是 kernel lockdep/KCSAN。
- OEM 归位在现有设备 mutex 下同步执行 HAL 给出的 I2C 序列及断电，避免遗留未回收私有线程；这与原厂后台线程的完成时序不同，必须验证 HAL 超时、共享 CCI/电源及关闭重开。没有新增私有固件文件，没有执行实机烧写或机械动作。
- 电压/温度/功率阈值、DT、安装和加载列表不变。多 Buck 分流、折叠专用拓扑以及未定义的 BAA/BASP 私有布局未伪造实现；无线 BAA 设置明确返回不支持。
- 仍需匹配 OS4.0.7 的 HAL/固件、生产工具链构建、最终 DTB/DLKM/镜像，以及插拔/PD/PPS/QC、无线充入净电量、反充、保护退充、相机开流/多摄/重开和待机实测。没有据此宣布所有硬件缺口清零。


## 2026-11-28：四类有线缺口合并收尾（历史批次）

基于 `669785f`。本节覆盖前面所说的四类**有线源码缺口**，以下历史章节的“仍需完成”以本节为准。此次一次提交启充、保护、停充和串行化的相关修改；完整 MCA 生产启用、最终镜像和真机验收仍有独立门槛。

| 范围 | 本批源码修复 | 验证 |
| --- | --- | --- |
| 并行 Buck 错误处理 | 复测前批并行 helper 的 MIN 限流、失败回滚与 dirty 重试；补齐 Buck 主/从使能失败回滚和首个 errno。单 CP PMIC 的输入/FCC/VTERM 改为普通 MIN 票，成功才缓存，失败先暂停再清理 | 并行 helper、完整样本、PMIC/VTERM 每步 I/O 失败、保留其他客户端限流 |
| remove / shutdown | QC 完整停充之后，再独立尝试输入暂停、零 FCC、每个实际 CP 关闭、已关 CP 的 ADC 关闭、FG fastcharge 复位。Buck 独立尝试各配置芯片输入归零/关闭/ADC 与 FG。reboot 先停任务和硬件，后续 remove 仍能完成注销释放 | 生命周期所有 probe 故障点、重复清理，以及独立关断失败注入；故障不能被当作物理停充成功 |
| 启充与保护接口 | PPS/QC 的 ADC、模式、升压、使能、读回、电流和超时检查；任何开启失败走受检查停充。动态变比先停旧路径再开新路径，清除固定 PDO 回退标志。恢复所有已配置 CP 的 UCP；VFC 有步数边界和最终读回。SOC/电压/电流/温度错误不会使用半更新样本；表尾阶段不越界；修正低于再充阈值却被阻止再充的判断。sysfs 先完整校验，模式/路径更新需先停活动充电，接口返回实际错误 | 实际 start/open、QC tuner/retry、动态变比、采样、阶段边界、PMIC/VFC 和模式/路径解析函数，ASan/UBSan |
| 并发状态切换 | QC 的事件、monitor、VFC、PTF 与硬件状态转换由 data_lock 串行；保护投票在锁外分发，回调用 trylock，竞争时保留目标、排队并返回 EAGAIN。数据锁内不同步等待 worker；卸载锁外禁用并等待任务。断开先发布中断标志，成功停充后才清旧状态。运行计数器改为实例字段；独立限制值用 READ/WRITE_ONCE | 实际入口锁的 100 次 pthread 并发调用、回调锁竞争、断开先中断再等待、保护 errno 保留；不能外推为 kernel lockdep/KCSAN 已通过 |

**构建与回归**：30 个主机脚本全部通过。Clang/LLVM/LLD 19.1.7、WERROR/CFI/MODVERSIONS 开启下，先通过四个充电策略对象，再在本地临时启用 `MYRON_MCA_COMPLETE_SERVICES=m` 及依赖，对完整 MCA 子树完成 55 条编译/组合链接任务；最终改动再次增量编译通过。详细脚本、SHA256、对象清单和范围见 `mca-wired-completion-validation-20261128.json`。这仍是 ARM64 对象/组合对象构建，**没有完整 Image、严格 modpost、最终 .ko 或刷机包通过记录**。

**实际剩余**：

- 完整 MCA 的 JEITA/保护执行端、事件来源和原厂边界、GLINK 所有权及无线策略仍须整链集成核验；本次未宣称整套 MCA 生产可用。
- Nezha 单 Buck 以外的多 Buck 电流分配仍返回 `-EOPNOTSUPP`；同时设置 single-CP PMIC 和 parallel Buck 的冲突配置在 DT 解析时返回 `-EINVAL`。没有猜测硬件分流值，也没有改变原有 DTS 功率/电压/温度阈值。
- 生产工具链全量构建/modpost、最终 DTB/DLKM、USB 插拔与快速重插、PD/PPS/QC、保护退充、reboot/shutdown、待机和实机锁检查尚未验收。硬件拒绝关断写入时，代码只能保留错误并尽力继续关闭其他路径，不能保证物理关断。
- BAA/BASP 私有布局、折叠专用拓扑、无线和相机的既有缺口不由这批有线修改宣告完成。无效的 legacy cur_ratio/volt_dec/current-limit sysfs 写入现在明确返回不支持，因为原实现没有消费这些值。

仓库生产 defconfig、安装/加载列表、设备树、模块仓库与 manifest pins 不变；完整 MCA 仍未启用。本地完整服务配置仅用于编译资格检查。

## 2026-11-28：并行 Buck 事务、单/双 CP 切换及退出停充

基于 `3321769` 接续。此节更新前一轮的并行 Buck helper、CP 路径切换与 QC remove/shutdown 缺口，**不是完整有线策略或基础功能全部完成**。

- **并行 Buck**：移除函数静态启停标记，改为实例状态与独立 mutex。先暂停输入，再设置频率和限流，全部确认后恢复输入并启动 AICL；确认成功才缓存生效值。失败返回首个错误并回滚，回滚失败保留 dirty 状态供下次重试。单/双 CP 的实际角色逐个检查，不向 CP 后端传 DUAL 作为芯片索引。
- **限流边界**：该 helper 改用普通 MIN 投票 `parallel_qc`；新限流建立后只撤本策略自己的 `wire_qc` 零电流票，保留温控/JEITA 等其他客户端的限流。停用先暂停输入、恢复自己的零电流票，再清理并行限流。没有上调 DTS 电流、功率、温度或电压参数。独立的 `pmic_single_cp_charging` 旧 override 路径仍未重构，不能把本节结论外推到它或两个功能同时配置的组合。
- **强制停充**：不再要求电流落入运行时滞回区间才能关闭并行 Buck；停充时电荷泵已关闭或传感器失效不能跳过清理。运行调节和停充调用方均检查 helper 的返回值。
- **完整电流样本**：先验证 CP 索引，再检查所有本次读取；用宽类型累加并检查负值和溢出，全部成功才发布总电流，读取失败不留下半更新样本并返回后端 errno。
- **单/双 CP 路径切换**：双转单必须完成关闭与 ADC 停用才更新工作角色；单转双检查 ADC、模式、使能、等待、读回及最小电流，每个失败都关闭新增 CP。回滚失败设置 stop_pending；monitor 收到切换错误进入已有停充路径。低电流未成功开通的 CP 不再遗留开启。
- **QC remove/platform shutdown**：等待接口、owned voter 与三个 worker 退出后，调用已检查的 CP/FG/适配器停充，再释放电池参数。teardown 保持 Buck 输入暂停，不执行正常运行停充的回退放行，不再只尝试关闭 CP。错误会记录并保持失败状态，但驱动卸载后不能异步重试，仍不能声称 I/O 失败时物理硬件已停止。reboot notifier 记录停充失败。
- **旧测试修复**：DTPT route 测试桩补齐前轮已加入的 JEITA stopping/READ_ONCE，并验证停止后的事件被拒绝。

验证见 `mca-wired-transitions-validation-20261128.json`：25 个主机检查通过；新增生产函数故障注入覆盖 12 个启用失败点、5 个清理失败点、首错/回滚、MIN 限流、双实例、同实例 pthread 竞争以及 CP 切换。使用完整源码和固定模块 UAPI，Clang 19.1.7 在 gki + canoe + nezha 配置上对 quickchg、Buck、JEITA、thermal 四个生产翻译单元完成 ARM64 Kbuild，输出为 AArch64 ELF；WERROR、CFI、DWARF module version 配置开启。宿主缺少生产 Rust/BTF 工具链，局部编译关闭 Rust/BTF/自动模块签名；**这是四个对象编译，不是完整 Image、模块链接/modpost、镜像或实机验证**。仓库生产配置未改变，完整 MCA 仍未启用。

**接续仍需完成**：

1. `pmic_single_cp_charging` / VTERM override、动态 CP 比率切换、其余启充/传感器/保护 I/O 的完整错误处理，以及 Buck 本体多芯片分配接口。
2. 全局事件、monitor、调压/调频与 stop 的串行化及重入/取消等待；本次 mutex 只串行化并行 Buck helper，pthread 测试不代表内核 lockdep 或完整 workqueue 无竞态。
3. 初始在线状态、disconnect 后保护票清理、完整保护提供者与原厂事件边界，之后才可评估完整 MCA 启用。
4. 生产 ARM64 全量编译/modpost、DTB/DLKM/镜像及 17U USB 插拔、PD/PPS/QC、过温退充、充电功率与待机实测；无线与相机仍按现有 P0 清单推进。

## 2026-11-28：有线功率查询、停充错误恢复及保护事件

基于 `86de4ff`，继续处理有线充电。本节更新上一节的 SIC 查询和部分停充缺口；完整 MCA 策略仍未启用。

- **SIC 功率查询**：检查 quickchg 状态和两类 adapter power API 返回值，使用 unsigned 输出，拒绝零功率、负状态功率与超过现有 120W 表范围的数据。失败时不覆盖已有 SIC/用户限流；暂时失败排入现有温控任务重试。功率查询失败不阻塞已有有线限制与无线限制的重放，永久功率错误也不吞掉供应者未就绪的独立重试。普通非 QC/PPS 电源切换清掉旧适配器派生 SIC 值，保留用户 SIC；断开即清理功率查询状态，不必等 voter 就绪。没有增加新功率档或提高原表电流。
- **PD/PPS/QC 请求**：返回实际协议后端错误；未知协议明确不支持，活动 APDO/QC 参数拒绝非正/逆序范围，保留既有上限钳制。固定 PDO 回退独立于旧 APDO 的最小电压，避免已允许回退 5V/9V 却被旧 APDO 下限阻断。固定 PDO 探测和 APDO 选择都先检查数量边界。
- **停充核心顺序**：取消 VFC 调节，尝试关闭实际配置的主/从电荷泵，并尝试关闭 FG fastcharge；错误保留首个 errno。只有这些步骤成功，才继续默认频率和适配器回退。在线时启用读回所需 ADC，只有请求成功、读取成功且 VBUS 为正并低于原有 12000mV 阈值，才继续模式/自身投票清理；最多 10 次尝试，零值、负值、读取失败和电压未下降不能伪装成功。`pmic_chg_need_fixed_volt` 路径保持 5V 请求，不再紧接着抬回 9V；其余路径保留原有目标选择。这不是严格的“已达到请求电压”测量证明，阈值未改变。
- **失败后的状态与重试**：失败保留 `stop_pending` / stop_charging，由已有 monitor delayed work 重试；monitor 和 charge-action 前置检查优先处理未完成停充，不能直接重启快充。禁止/使能 voter、保护事件返回停充错误。启动失败也使用同一受检查的停充路径，不再先撤限制再停 CP。USB 断开按事件关闭 online，停充失败不清空协议/过程结构；物理断开后不再要求适配器响应。单 CP 不等待不存在的从 CP；非折叠设备不 rerun 缺失的 flip voter。
- **保护事件及监测**：接口防烧、BTB、进液、CC 短路、VBAT OVP、CBOOT、PPS PTF 等已有投票路径返回真实错误；sink suspend 仍尝试各 CP 和禁止票并保留首错。运行监测不再忽略 CP/FG 状态读取错误，双 CP 正常也必须继续检查 FG；非法工作 CP 索引拒绝，避免错误计数越界。没有据此宣称传感器、通知边界或所有保护提供者已接通。

验证：`mca-wired-validation-20261128.json` 记录 17 个 host 脚本通过，新增实际 SIC/query/retry 函数、实际停充/协议请求/保护事件/CP-FG 监测函数的故障注入。测试覆盖失败保持限制、无效功率/能力数组、两类功率 API、CP/FG/协议/ADC/投票逐步失败、10 次降压等待、重试、断开保存状态、单/双 CP 和首个错误；复测前轮生命周期、voter、smartchg、温控与 JEITA。新测试的 monitor/pre-charge pending 分支另有源码顺序断言，**没有执行完整 monitor/pre-charge 状态机或真实内核 workqueue 并发**。硬件/通知/工作队列使用桩，host cc + ASan/UBSan 不等于 ARM64 内核编译或实机结果。

**有线仍需完成**：

1. 完整 JEITA、端口/电池保护执行端、原厂事件边界和初始在线状态；完整策略启用前仍需逐项验证。
2. 并行 Buck helper 仍有函数 static 状态和被忽略的执行错误；折叠专用分支、部分 sysfs 模式开关与 disconnect 后保护票清理还未达到完整错误传播。上述路径未被新测试的 stub 当成完成证据。
3. remove/shutdown 仍为前轮 CP 关闭尝试，未接入本轮运行时完整降压/FG 复位；不能声称整个生命周期停充完成。并发事件/调节/重试的串行化、重入与取消等待也仍需内核验证。
4. 电荷泵进入/切换路径及其它传感器读取仍有错误处理缺口；本轮只覆盖所列读取和停充函数，不代表所有 I/O 都已检查。
5. 生产工具链 ARM64 Kbuild/modpost、最终 DTB/DLKM/镜像，以及 17U 实际 USB 插拔、PD/PPS/QC、过温/故障退充和待机验收。当前没有新的实机充电功率结论。

模块树 `e1864d6`、设备树 `91998b3`、manifest pin 和 MCA 配置/加载范围不变。无线与相机缺口沿用下节清单；卫星和 BASP/BAA 私有扩展不进入类原生基础必做范围。

## 2026-11-28：温控错误恢复及 Buck/快充限流传递

基于 `4237e3c`。本节更新前几轮温控投票错误及部分 Buck/QC 限流缺口，不代表整条保护链已经完成。

- **温控失败可见、可重试**：有线、无线和已有 flip 应用函数返回实际错误；遍历剩余限制后保留首个错误。sysfs、cooling、无线移除限制导出接口、smartchg 和插拔事件把执行错误交还调用者。失败请求保留期望状态；现有 delayed work 重放当前目标，避免恢复旧请求。有线供应者失败不阻塞已就绪的无线供应者。无设备、无参数、永久不支持与暂时未就绪分开处理。
- **释放与插拔**：仅所有撤票成功后标记温控已移除。断开按事件身份判定，不再依赖 payload；失败清票使用独立 pending 标志重试，重连取消旧清票。普通离线重试不会无故清掉新设的 SIC 目标。两个 SIC 输入都为零时清掉旧派生值。无线连接立即应用当前档位；第 11 列 xiaomi_car 仍未接入对应 voter。
- **拒绝非法输入**：sysfs 在修改状态前检查解析、负值、档位上限、布尔开关及无线支持状态。保留原有双电芯选择约定。没有把“请求已记录”等同于“硬件已执行”；cooling 的当前值仍为期望档位，不是硬件读回。
- **取消厂测覆盖**：移除开机首分钟 SMEM zero-speed 跳过温控的分支，以及把正输入限流抬到至少 1500mA 的覆盖。现有温控表和用户请求仍决定限流值，未提高任何保护阈值。这是共享驱动行为变更，也取消了这些路径原有的厂测绕过。
- **Buck/QC 下层错误**：Buck 的输入挂起及 5V/9V 限流回调返回下游 vote 错误；电压模式切换同时尝试输入、充电两路并返回首个错误。快充 single/multi 各三个模式的 fanout 不再吞掉错误。四个未实现的 multi-buck 电流/电压/终止电流函数明确返回 `-EOPNOTSUPP`；这不是增加多 Buck 支持，Nezha 默认单 Buck 路径不变。

验证：`mca-protection-validation-20261128.json` 记录 15 个 host 脚本通过。新增实际温控函数的 30 个失败点、同值重试/新请求替换、撤票失败、独立供应者、sysfs/cooling 边界与断开清理；新增实际 Buck/QC 限流回调的逐通路失败、首个 errno、全部分发目标和低于 1500mA 的原值传递。复测 provider 生命周期、owned voter、smartchg、JEITA、charge interface 和固定 DT 表。使用 host cc + ASan/UBSan、硬件/工作队列/SRCU 桩；没有 ARM64 Kbuild/modpost、真实并发或实机通过证明。没有将多个 vote 变成原子事务，也没有增加 sysfs/事件之间完整的状态串行化。

当前基础功能剩余项：

| 范围 | 未完成及证据边界 |
| --- | --- |
| 有线充电保护 | SIC 适配器功率查询仍需错误传播/重试；JEITA、端口/电池保护的完整执行链与原厂事件转换；快充适配器降压、FG fastcharge 复位和整条停充顺序；初始在线状态及并发状态切换仍需核对。 |
| 无线充电 | basic/quick wireless 的 owned voter、外部注册失败清理和完整退出；SC96281 控制/FOD/保护联动。审计发现 quick wireless 的 remove/shutdown 仍为空、三类注册未检查；basic wireless 也未完整注销，不能直接启用。flip voter 仅被查找，并非被证明是 Nezha 硬性依赖。 |
| 相机 | OIS/actuator 私有 ABI、固件、停驻/供电协议及 HAL 开流、重开、多摄验证。SEM1218S zoom 不等于 OIS 已完成。 |
| 触摸、基带、Wi-Fi、蓝牙 | 已有源码和 DT 入口不能替代最终固件/HAL 配套与本轮 17U 实机验证；当前没有新日志据以宣布缺口清零。 |
| 构建与交付 | 生产工具链完整 ARM64 内核/modpost、最终 DTB/DLKM/签名镜像及启动、充电、通信、相机、待机验收。 |

完整 MCA SERVICES/COMPLETE 和未验收保护策略保持关闭。模块树 `e1864d6`、设备树 `91998b3`、manifest pin 与加载范围不变。卫星及未经验证的 BASP/BAA 私有扩展仍不作为类原生基础功能必做项；无线掉电的 Myron 记录不作为 Nezha 验收依据。

## 2026-11-28：smartchg 生命周期、供电切换与类原生取舍

基于 `130fb86`，继续处理基础充电公共层。本节更新此前 smartchg 所有权/全局对象缺口，并把未经验证的厂商私有 BAA 扩展从本分支基础适配范围排除；完整 MCA 策略仍未启用。

- **smartchg 的 3 个自有 voter** 使用 owned API；probe 检查参数、投票器、策略、两条通知链、全局发布和 sysfs 的结果。失败/remove/shutdown 按身份撤下全局实例，同步注销 sysfs/策略/通知链、解绑 voter，禁用并等待全部 3 个 delayed work。保持下游限制，未把注销当作硬件已停充证明。
- **6 个全局导出接口** 用 SRCU 覆盖完整访问；失败/重复 probe 不得清空其它设备实例。内部 sysfs 控制和场景操作直接使用所属设备，避免旧设备的调用写入新实例。场景上报历史也改为每设备状态。
- **有线/无线切换** 分开记录 USB 和无线在线状态；只在首次上线时启动、最终离线时取消监控并清理 SOC 控制，重复事件不重置状态。测试覆盖两种切换顺序；不把顺序事件模型当成完整内核并发证明。
- **错误与重试**：FV/ICHG/FCC 三类投票回调遍历已有提供者、保留首个真实错误，完全没有后端时返回 `-ENODEV`。FV/ICHG 的已应用缓存只在全部调用成功后更新；插拔和 DTPT 投票错误上返。循环次数读取失败保留原限制；投票失败时即使目标未变化，后续监控仍交由 voter 层重试。scalar sysfs 返回投票错误，并检查电池倍率乘法溢出；循环参数按实际行数读取，拒绝非法 cell_type、负值和逆序阈值。
- **明确排除 BASP/BAA 私有覆盖**：公共头原本明确标注布局仅从用法推测，不能据此解释原厂数据。本分支不再注册 `/dev/smart_charge_cdev`，移除其 ioctl/mmap 和 blob 分发，不再处理原厂 `enable_fv_dec_by_cc` 覆盖请求；快充 BAA 回调明确返回 `-EOPNOTSUPP`，不读取输入、不替换正在使用的电压/stage 表。保留 DT 参数及普通 scalar/SOC/温控接口。这不是“已实现 BAA”，依赖该私有节点的原厂电池老化增强不在当前兼容承诺内；本次为共享 smartchg 源码变更，不局限于单个调用方。
- **Nezha 电池表稳定性**：普通直板 USB 事件不再进入仅用于折叠 base/flip 的循环参数重解析，避免反复分配和替换相同表。折叠机运行时表更新并未在本轮宣布完成；Nezha 不依赖这条路径。

验证：`mca-smartchg-validation-20261128.json` 记录 13 个 host 测试脚本通过；新增实际 smartchg probe/stop/全局导出/事件代码故障注入、SRCU 等待模型、20 次重绑，参数/worker 错误重试，以及 QC 明确拒绝私有覆盖/跳过折叠重解析。原注册层测试覆盖剩余 7 个实际分发函数，新增后端失败回传；BASP 不再是可执行的分发入口。使用 host cc + ASan/UBSan 和内存/注册/工作队列桩；不是 ARM64 全量编译、内核并发验证或实机充电结果。

**基础功能仍未完成**：温控投票失败的完整传播与重试；JEITA、端口/电池保护、原厂事件边界、适配器降压和整条停充顺序；SC96281 无线控制/保护接入；相机 OIS/actuator 私有 ABI、固件、停驻与多摄；生产工具链 ARM64/modpost、最终 DTB/DLKM/镜像，以及 17U 触摸、通信、相机、充电和待机实测。此前的硬件状态不因本轮单元测试而升级。模块树 `e1864d6`、DT 树 `91998b3` 和配置启用范围不变。

## 2026-11-28：Buck、快充、温控提供者成组修复

基于 `9561c19`，本轮连续处理三个提供者的初始化、发布、失败回退、remove/shutdown 和参数边界；不改变完整 MCA 策略的启用范围。以下条目更新上一节所列的 Buck/quickchg voter 和 thermal 生命周期缺口。

- **Buck + quickchg 共 22 个自有 voter** 改为 owned API。中途创建失败会按设备身份解绑已创建对象，返回实际注册错误；旧消费者缓存的地址由公共 voter 层保留。所有自有 voter 回调拒绝未就绪/停止状态。charge interface 使用每设备 ops，smartchg 使用注册时复制的局部 ops，不再改写共享模板。
- **成组注销与任务退出**：检查策略、charge interface、smartchg、通知链和 sysfs 的注册结果。退出先停止接入新请求、同步注销外部回调、解绑 voter，再逐一禁用并等待 Buck 的 9 个 / quickchg 的 3 个 delayed work，防止取消后被其它任务重新排队。Buck 最后尝试停充，quickchg 最后尝试关闭电荷泵；硬件失败会记录，不能据此宣称适配器已降压或硬件已停充。不清除已有 JEITA/温控限制，不主动开启替代通路。
- **Nezha 的快充依赖**：只有 `support-base-flip` 才等待 `flip_charge_curr`，修复直板机等待折叠机 voter 的问题；缺少 smartchg_delta_ichg 时不把负错误码当电流调整量。电池表选择器将普通/折叠选择归一化，检查负角色、表长及实际所选表；FG 未就绪保留 deferred probe，I/O / 不支持 / 参数错误不再全部转为 deferred probe。普通表解析失败不会被下一张表成功覆盖，临时获取的全球 OF 节点在全部退出路径释放。当前持有的普通/折叠温度、电压、stage 表在读者和任务退出后释放，涵盖 probe 失败。
- **thermal 全局入口** 使用 SRCU 等待访问者，重复/失败 probe 不得清除其它实例；cooling device、策略、smartchg、sysfs、日志和重试任务都有清理。移除函数内共享 static 温控状态，改为每设备状态。无线 voter 已就绪时仍继续等待缺失的有线 voter。
- **温控参数边界**：无线档位先选值再检查，普通/折叠路径均拒绝负档位；cooling 最大档位不再多报一档，拒绝超过上限的 unsigned long 状态；有线/无线/折叠表错误会终止 probe，折叠表 max 与实际索引一致。缺少可选 `wired_sic_select` 不再阻塞不使用该功能的设备。

验证：11 个 host 测试脚本通过，见 `mca-provider-validation-20261128.json`。新增实际 Buck/quickchg probe/stop 的逐阶段故障注入、22 个 voter 解绑、回调注销、迟到任务重排、重绑与参数释放计数；新增实际 thermal 全局入口的并发等待/失败 probe、cooling 和无线越界、供应者重试；新增实际快充电池表选择器的模式/角色、FG 错误、读取失败与 OF 引用释放。复测 owned voter、错误重试、JEITA、smartchg 注册层、charge interface；温控表用当前 DT pin 的 150 + 165 项检查。模型使用 host cc + ASan/UBSan，SRCU/workqueue/硬件使用桩，绝不是 ARM64 内核运行或硬件验收。显式计数验证所测参数分配的释放；不宣称通过 LeakSanitizer 或覆盖所有运行时分配。

**仍阻塞完整充电策略启用的源码项**：smartchg 自有 voter / 全局对象 / cdev / mmap 生命周期；快充运行时电池表替换与 BAA 输入边界/并发；温控投票失败的完整传播与重试；JEITA、端口/电池保护、原厂事件边界和无线 SC96281 的完整执行链。quickchg 退出仍需核对适配器降压、FG fastcharge 及整条停充顺序。本轮没有把全部 MCA 提供者宣布为可卸载，也没有启用缺少保护链的快充。

**其它基础功能仍待完成**：相机 OIS/actuator 私有 ABI、固件/停驻/供电协议及多摄；生产工具链的完整 ARM64/modpost、最终 DTB/DLKM/签名镜像；17U 触摸、相机、充电、基带、Wi-Fi、蓝牙及待机实测。本机没有新硬件日志，不能以 Myron/K90PM 的结果代替。此次只修改内核仓库；模块和设备树 pin 分别保持 `e1864d6`、`91998b3`。

## 2026-11-28：共享 voter 提供者解绑与 JEITA 实际退出路径

基于 `5e37256`，本轮修复以下源码路径，仍不打开完整充电策略配置：

- **可解绑的 owned voter**：新增 `mca_create_owned_votable` / `mca_detach_owned_votable`。提供者身份不匹配、重复注册、试图接管 legacy voter 均拒绝；所有回调仍在原 vote_lock 内执行，解绑取得同一把锁，等待已有回调后清空 callback/data。缓存的对象地址和既有投票保留，投票、override、rerun、force_active 在无提供者时返回 `-ENODEV`，有效结果查询也不伪装成功。重新绑定必须名称、类型和默认值一致，由首次有效投票或显式 rerun 应用保留的限制。仅模块退出、依赖使用者已退出后释放保留对象；传统 destroy 不可释放 owned 对象。legacy 创建/销毁合同没有被自动升级，仍需逐提供者迁移。
- **JEITA 接入实际注销**：策略注册和 smartchg 注册均检查错误；smartchg 使用局部 ops 副本，静态模板不再写入设备 data。失败回退/remove/shutdown 先标记停止，按身份同步注销两类回调，再取消监控任务；停止后的事件、状态查询和 smartchg 回调拒绝继续操作。注册前初始化 online 状态，避免 probe 后段覆盖期间已收到的 Nezha 插拔事件。
- **去除 Nezha 不需要的依赖**：只有 DT 明确声明 `support-base-flip` 才创建折叠机 `flip_charge_curr`，并使用 owned voter；监控重试不再重复创建。普通直板路径不依赖此 load-switch voter。绑定时不提前把默认电流写入硬件，由首次温度计算投票应用限制。
- **退出保护行为**：监控停止后保留原有温度限制，尝试向已有 `chg_enable` voter 投入 JEITA 禁止充电票；失败记录错误，不能当作硬件已停充证明。新提供者需要实际温度采样才能重新启用。没有清除限温票来制造“充电恢复”。

验证通过：`test-mca-owned-voter.py`（生产 voter 全文件 + pthread/debugfs/分配模型）、`test-mca-jeita-lifetime.py`（实际 probe/事件/退出函数，通用与 Nezha 两种配置）、原 `test-mca-voter-errors.py`、更新的 `test-nezha-jeita-events.py`、`test-nezha-jeita-parser.py` 的内置畸形/失败用例。测试使用 host cc + ASan/UBSan，覆盖并发解绑等待、旧数据释放后的缓存句柄、同名并发创建、20 次重绑不增长分配、模块退出清理、供应者/注册失败、重复 probe、停止后不重排任务。此轮 parser 回归使用内置 fixture，不是重新核对完整 stock DT。

**仍未完成**：Buck/quickchg/smartchg 自有 voter 向新所有权接口迁移；smartchg 全局对象与 cdev/mmap 生命周期；thermal 全局入口及 cooling device 退出；完整 JEITA/温控/保护执行链和启用；无线接收器；OIS/actuator ABI、固件与实机多摄。JEITA 借用的 Buck legacy voter 仍依赖其原提供者生命周期，不能据此宣称整个充电框架已可安全卸载。没有本轮 ARM64 内核/modpost、最终 DTB/DLKM、充电或相机实机通过记录。模块树、DT 树及 manifest 配套 pin 未变。

## 2026-11-27：BMD 退出路径、smartchg 注册层与 voter 错误重试

基于 `c7aaf6d` 继续修复充电框架，配置及 DT 启用范围不变：

- **BMD 资源与退出**：ADC 获取错误和 GPIO 供应者的 `-EPROBE_DEFER` 原样返回；GPIO 改用 devres 输入申请，遵循原有单 `btb_gpio` 绑定，两个通道引用同一 GPIO 时只申请一次。删除有限次数的后台 GPIO 重试及全局计数。全部任务先初始化，才公开策略回调；检查注册/sysfs 错误，失败时先同步注销再取消工作。remove/shutdown 共用幂等清理。未取得有效采样前不报告电池连接正常，GPIO/ADC 读取错误不伪装正常；初始延迟上报同步更新查询状态。没有状态处理器的 INT 方案明确拒绝。
- **smartchg 接口注册层**：选择性利用附件的 SRCU 思路，但注册时复制 ops，避免调用方改写共享 static 表改变已注册 data；拒绝重复注册，按 `type + data` 身份同步注销。覆盖 8 个现有分发函数，移除函数内共享 static 临时 ops 指针；模块退出释放注册表副本。接口声明写明必须先注销、再释放回调上下文，且不能在回调内注册/注销。**这不是完整 smartchg 卸载修复**：既有 provider 仍需接入注销；全局 info、cdev/mmap、voter、通知链及工作退出还有缺口。
- **voter 错误恢复**：硬件回调失败后，同值投票仍会重试；rerun 失败也保留重试条件。恢复普通限制失败时保留 override；强制状态切换失败回滚其标志。无回调的纯聚合 voter 可使用 override；从未投票时恢复默认限制，不传 `-EINVAL` 作为硬件值；补强制期间 override 客户端记录及非法类型分支解锁。get_effective_result 仍是软件选举目标，不是硬件读回值。**未解决全局 voter 的持有者引用/所有权和同步销毁。**

新增验证：`tools/test-mca-bmd-lifetime.py`、`tools/test-mca-smartchg-registry.py`、`tools/test-mca-voter-errors.py`，提取真实 C 函数运行 ASan/UBSan。覆盖供应者延迟/错误、重复注册、发布后失败清理、停止后的任务、所有 8 处分发、调用方 ops 改写、注销等待、内存申请失败、同值重试和 override/强制失败。SRCU 使用 pthread rwlock 模型，BMD 使用工作队列/devres 桩，不能替代内核并发和实机验证。新分配的注册表副本有显式分配计数断言，不宣称完成 LeakSanitizer。

**尚未完成**：完整 ARM64 内核/modpost、最终 DTB/DLKM/镜像及实机验收；voter/provider 所有权；smartchg 设备全生命周期；JEITA/温控/保护执行链；无线接收器和快充；OIS/actuator 私有 ABI、固件、停驻与多摄实测。BMD 也未在 Nezha 启用：官方板级配置为 IIC + GPIO（`btb_bmd_scheme=<3 1>`），其 FG chip-ok 语义/执行端仍需核对，不能把当前只读电池桥接当作完整 BMD 支持。完整版服务配置继续关闭。

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
