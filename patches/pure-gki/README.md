# Meizu 20（kalama）GKI 兼容补丁集

目标：让纯 ACK `android13-5.15-lts`（5.15.195，commit 8a8f52308945）能够加载魅族原厂
`vendor_boot` / `vendor_dlkm` 中全部 643 个 `.ko`，且所有导入符号的 CRC 与原厂内核一致。

## 0001-android-gki-export-meizu-kmi-symbols.patch

魅族模块导入、但 ACK 未导出的三个内核符号：

| 符号 | 导入方 | 原厂导出类型 | 原厂 CRC |
|---|---|---|---|
| `__tracepoint_android_vh_extfrag_for_order` | `mz_compaction_opt.ko` | `ksymtab_gpl` | `0xf18a8605` |
| `__tracepoint_android_vh_smartzram_tune_swappiness` | `smartswap_zram.ko` | `ksymtab_gpl` | `0x1523d65f` |
| `mem_cgroup_id_put2` | `smartswap_zram.ko` | `ksymtab_gpl` | `0xf78296e5` |

`mz_compaction_opt.ko` 在 `vendor_boot/lib/modules/modules.load` 中，是开机第一阶段
必须加载的模块；缺符号会导致 `finit_module` 失败，Android init 在 strict 模式下打印
"Failed to load kernel modules" 后 abort，表现为无限重启。另两个符号供后续按需加载的
魅族 zram 模块使用。

`mem_cgroup_id_put2` 是 `mem_cgroup_id_put()` 的 out-of-line 导出包装，函数体必须保持
内联调用 `mem_cgroup_id_put()` 以维持原厂 CRC。

## 0002 / 0003：补回原厂内核的 hook 调用点

`extfrag_for_order()` 与 `lru_gen_shrink_lruvec()` 在原厂内核中分别调用了上述两个
tracepoint（已用原厂 vmlinux 反汇编确认调用点：`extfrag_for_order`、`lru_gen_shrink_lruvec`）。
只导出 tracepoint 而不调用，模块能加载但魅族内存调优功能失效，因此两个调用点必须补齐。

`#include <trace/hooks/mm.h>` 必须放在文件内最后一个 `EXPORT_SYMBOL` 之后、调用点之前：
该头文件在 `__GENKSYMS__` 下会引入 `linux/mm.h` 与 `mm/slab.h`，放在文件顶部会改变
同文件既有导出符号的 genksyms CRC（实测 `register_shrinker`、`shrink_slab`、
`try_to_free_mem_cgroup_pages`、`__mod_zone_page_state` 等全部漂移）。

## 0004-of-address-keep-pci-host-bridges-off-default-flags-bus.patch

5.15.127 引入的 `default-flags` bus 以 `#address-cells == 3` 作为匹配条件；魅族 DTB 的
`qcom,pcie@1c00000`（compatible `qcom,pci-msm`）没有 `device_type = "pci"`，会被该 bus
抢走并把 ranges 的第一个 cell（PCI 地址空间类型）当作 flags，导致根总线丢失
`IORESOURCE_MEM`、BAR 分配失败、WiFi 无法 probe。原厂 5.15.119 没有该 bus，等价于
plain default bus，因此本补丁排除该节点以恢复原厂行为。

## 0005-misc-add-xiaomi-millet-netlink-bridge.patch

HyperOS 4 的 `millet_monitor`（`/system_ext/bin/millet_monitor`）通过
`NETLINK_MILLET = 31`（与 `ro.millet.netlink=31` 对应）与内核通信，用于应用冻结、
binder 事务统计与信号上报。移植系统沿用小米框架，缺少该驱动时 `millet_monitor`
反复重启（实测 19 次循环）。

源码取自小米 gold（`Star-caorui/android_kernel_xiaomi_gold-xiaomi_modules`
@ `OS3.0.5.0.VNQMIXM` 的 `millet/`，2019 小米原始版权，协议布局与本机
`ro.millet.netlink=31` 匹配），按 5.15 GKI 适配：

- `binder_gki.c`：`android_vh_binder_alloc_new_buf_locked` 去掉 `should_fail` 参数；
  `android_vh_binder_preset` 去掉 `proc` 参数；`binder_transaction` 无
  `from_pid/from_tid/start_time`，改用 `t->from->proc->pid` 与 `t->from->pid`。
- `millet.h`：直接使用内核自带 `frozen()` 与 `cgroup_task_frozen()`，不再自带
  `task_frozen()`（6.6 写法）。
- 全部子模块由 `module_init` 改为内置 initcall（core 用 `device_initcall`，其余
  `late_initcall`），保证以 `=y` 编入 Image 后仍按依赖顺序初始化。
- 顺带修复原源码缺陷：`millet_data` 栈变量未初始化即发送（信息泄露）、
  `frozen_uid_min` 的 `module_param` 类型与 `int` 定义不一致、`sscanf` 无界写入。

`CONFIG_XIAOMI_MILLET=y`，代码位于 `drivers/misc/xiaomi/millet/`。

## 0006-thermal-add-xiaomi-thermal-message-interface.patch

HyperOS 的 `PowerKeeper` / `PowerInsight` 与 thermal 守护进程通过
`/sys/class/thermal/thermal_message/*`、`/sys/class/thermal/power_save/*` 交互；
移植系统沿用小米框架但缺少该接口，`PowerInsight` 报
`calculateCpuCurrentPower, NO processorPower`、`NPU freq duration file not found`，
`PowerKeeper` 读不到 `board_sensor_temp` / `ambient_sensor_temp`。

源码取自小米 marble（`Pzqqt/android_kernel_xiaomi_marble` 的
`drivers/thermal/mi_thermal_interface.c`，含 `ambient_sensor_temp`），按 5.15 GKI 适配：

- 移除 `panel_event_notifier` 屏幕状态链（本机无 QCOM 面板通知扩展；`screen_state`
  节点保留默认值 0）。
- 移除 `#include "../base/base.h"` 与 `thermal_core.h` 依赖。
- 属性写入由 `snprintf(dst, size, buf)` 改为 `strscpy`，消除格式化字符串漏洞；
  `sscanf("%s")` 改为 `sscanf("%127s")`，消除栈溢出。
- `late_initcall_sync`，保证 thermal 核心与 cpufreq 就绪后创建节点。

`CONFIG_MI_THERMAL_INTERFACE=y`、`CONFIG_MI_THERMAL_MULTI_CHARGE=y`，代码位于
`drivers/thermal/mi_thermal_interface.c`。

### 已知缺口（不属于本补丁）

`PowerInsight` 还读取 `/sys/class/xr_pmodel`、`/sys/class/devfreq/npu_freq/npufreq_usage`、
`/sys/class/power_debug/*`、`/sys/class/xm_power/*`，`PowerKeeper` 还读取
`perf_status`、`ipa_cdev_load`、`ipa_dump_info`、`display_status`、`therm_log_enable`；
这些在公开小米内核源码中检索为 0（疑似闭源模块），本补丁不包含。

## 0013-droidspaces-sysvipc-kabi.patch

Droidspaces 在 GKI 上启用 `CONFIG_SYSVIPC` / `CONFIG_IPC_NS` / `CONFIG_POSIX_MQUEUE`
时，`struct task_struct` 的 `sysvsem` / `sysvshm` 会插入结构体中部，改变后续字段偏移，
魅族 vendor 模块的 CRC 校验失败后拒载，表现为无限重启。

补丁来自 ravindu644/Droidspaces-OSS 的
`Documentation/resources/kernel-patches/GKI/below-kernel-6.12/001.GKI-below-6.12-fix_sysvipc_kabi_6_7_8.patch`
（5.15 使用 `_6_7_8` 变体），把两个字段移入 `task_struct` 末尾的
`ANDROID_KABI_RESERVE(6..8)`，结构体大小与既有字段偏移保持不变。

## 0014-gki-defconfig-droidspaces.patch

按 Droidspaces 官方 GKI 配置清单启用 ABI 安全项：

- 必需：`SYSVIPC`、`POSIX_MQUEUE`、`IPC_NS`、`PID_NS`、`DEVTMPFS`、
  `NETFILTER_XT_MATCH_ADDRTYPE`
- 推荐：`USER_NS`、`IP6_NF_NAT`、`IP6_NF_TARGET_MASQUERADE`、`MACVLAN`、
  `NETFILTER_XT_TARGET_LOG`、`NETFILTER_XT_MATCH_RECENT`、`IP_SET`、
  `IP_SET_HASH_IP`、`IP_SET_HASH_NET`、`NETFILTER_XT_SET`、
  `TMPFS_POSIX_ACL`、`TMPFS_XATTR`

`CFS_BANDWIDTH`、`CGROUP_PIDS` 按官方说明保持关闭：二者改变调度器/cgroup 结构体，
无 padding 可覆盖，开启会导致 vendor 模块 CRC 失配。

## 0015-mglru-min-ttl-1000.patch

MGLRU 的 `lru_gen_min_ttl` 默认值由 0 改为 `HZ`（1 秒），对应
`/sys/kernel/mm/lru_gen/min_ttl_ms` 默认 1000，与设备运行态实验值一致，重启后保持。

## ksu-preinit-recovery.patch

KernelSU 的 preinit 在 `__init` 阶段把 runner 静态 ELF 放进 shmem，随后在 PID 1
执行 `/system/bin/init selinux_setup` 时把文件名换成 `/proc/self/fd/N` 交给
runner；runner 跑完模块 preinit 动作后再 `execve("/system/bin/init")` 回到真正的
init。

recovery 启动时 first stage 不挂载 `/system`（`DoFirstStageMount` 在 recovery
模式直接返回），`/system/bin/init` 是 ramdisk 里的 init；此时 runner 最后一次
`execve("/system/bin/init")` 失败，runner `return 127`，内核报
`Attempted to kill init! exitcode=0x00007f00`，recovery 黑屏后重启。

recovery 下 `/metadata` 未挂载，preinit 本来也没有动作可跑，因此按 AOSP
`IsRecoveryMode()` 同一判据（`/system/bin/recovery` 存在）在 hook 处直接跳过
preinit 并释放 runner，让原始的 init exec 继续；正常启动行为不变。同时把 runner
最后一次 exec 失败的日志改为 `<0>`（KERN_EMERG），以便本机控制台门限下仍能从
pstore 读到 errno。

该补丁在 `Setup KernelSU` 之后单独应用，路径为 `KernelSU/kernel/preinit/`。

## 验收判据

对产物 Image 重建符号表后，用 `kernel_os4/tools/verify_kernel_compat.py` 扫描 `vendor_boot` 339 个 +
`vendor_dlkm` 304 个 `.ko`：

- 内核级缺失符号数 = 0
- 内核导出 CRC 与模块 `__versions` 失配数 = 0
