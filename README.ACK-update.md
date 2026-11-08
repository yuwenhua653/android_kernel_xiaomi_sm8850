# Myron ACK 6.12.97 测试接入

这次更新将原生 Kbuild 核心树从 Linux 6.12.81 更新到 ACK
`android16-6.12-lts` 的固定提交
`17cce7bfbb9debdca995c7ce2a34da4f13c5aafc`（Linux 6.12.97）。
它不是 Linux 6.12.116，也不包含已经验证过的手机运行结果。

基于记录的 ACK 原始导入提交进行三方合并，处理了 8 个文件的 16 处冲突。
保留高通平台扩展，并适配 QRTR 节点回收与线程退出路径。另修复 ACK BTF
脚本在增量构建时追加重复 `.BTF` 段的问题。源码来源和逐项合并理由见
`android/myron-native/ack-update.json`。

## 取得测试分支

提供的 `myron-ack-6.12.97.bundle` 是增量 Git 包，要求本地存在原生分支提交
`821dfb2ebc7735b9169573554ad05a7a508f1ec9`。以下命令先获取该历史，
再从你当前的工作版本创建测试分支并合并更新，保留你当前分支的提交。
不会 reset 当前源码，也不会覆盖设备树或修改 manifest。

将下载文件放在 `~/Downloads/myron-ack-6.12.97.bundle` 后运行：

```bash
(
  set -eu
  cd ~/evo/kernel/xiaomi/sm8850
  bundle="$HOME/Downloads/myron-ack-6.12.97.bundle"
  test -f "$bundle"
  if test -n "$(git status --porcelain)"; then
    echo 'STOP: 内核工作区有未提交修改；请先自行提交或保存，再接入。' >&2
    exit 1
  fi
  upstream=https://github.com/yuwenhua653/oppo_oplus_realme_sm8850.git
  if test "$(git rev-parse --is-shallow-repository)" = true; then
    git fetch --unshallow "$upstream" myron/native-kbuild
  else
    git fetch "$upstream" myron/native-kbuild
  fi
  git cat-file -e '821dfb2ebc7735b9169573554ad05a7a508f1ec9^{commit}'
  git bundle verify "$bundle"
  git fetch "$bundle" \
    refs/heads/myron/native-ack-6.12.97:refs/remotes/myron-ack/6.12.97
  git switch -c myron/ack-6.12.97-test
  git merge --no-edit refs/remotes/myron-ack/6.12.97
)
```

若你的额外本地改动产生合并冲突，Git 会停在测试分支：逐项解决后再编译，
或用 `git merge --abort` 撤销本次未完成的合并。不要直接选整文件 ours/theirs。
测试分支名称已存在时上述命令也会停止，避免复用不明状态。

## 编译与验证范围

继续使用现有原生设备树的 envsetup/lunch 和正常 ROM 编译命令。
核心树仍位于 `kernel/xiaomi/sm8850`，外部模块与 DT 位于原来的两个
`kernel/xiaomi` 项目；没有新增 MYRON_DT_MODE、私有构建入口或资源变量。
建议使用新的 OUT_DIR，避免复用 6.12.81 的内核与模块产物。

详细实测结果和工具链固定版本见 `android/myron-native/ack-validation.json`。
这次主机验证使用 ACK 对应的 Android Clang r536225（LLVM 19）和
Rust 1.82.0.p2，启用了 Rust Binder、BTF、CFI 和模块版本检查。
这不能代替你本地 Clang 21 / Rust 1.93.1 的完整 ROM 构建验证。

本次不提供可刷入镜像。需要用你当前能启动的 ROM 工程重新编译内核及配套
boot/vendor_boot/recovery、system_dlkm/vendor_dlkm，保持同一构建来源。
不能把本次 6.12.97 的内核和旧版 6.12.81 模块混刷，也不要使用旧 R123
ramdisk 模板重新组装你当前 ROM 的镜像。

ACK 升级本身没有验证待机耗电改善。本次 DT 编译固定在既有基线
`b84c303a85a8f8b73d7fa3d4df37b57a601dd5b1`，不把另一分支的待机 DT
改动混入此次测试。保留现有音频 TFA 参数及 vendor_dlkm EROFS 配置。
