# 从这里开始

这份文档是给第一次接手项目的人看的 5 分钟总览。目标不是讲细节，而是先把“项目是什么、正式怎么跑、真源在哪里、边界在哪里”说清楚。

## 这是什么项目

这是一个 Windows 游戏自动化脚本项目，当前主线能力是：

- 自动抢购
- 自动上架
- 自动换号 / 换区
- 悬浮窗状态显示
- 本机网页查看与最小修改

代码入口仍是 `main.py`，但它不是日常人工启动入口。

## 正式目录与 live 数据位置

当前项目要同时区分两类目录：

- 代码目录：当前仓库根目录，也就是你正在阅读的项目目录。
- live 数据根目录：`C:\py666`

当前 live 根目录优先承载：

- canonical SQLite：`C:\py666\account_stats.sqlite3`
- 本机换号配置：`C:\py666\local_switch_account_config.json`
- 本机网页同步配置：`C:\py666\local_web_sync_config.json`
- 昵称模板目录：`C:\py666\nichen`

如果 `C:\py666` 中对应文件缺失，代码才会回退到项目根目录旧位置。

## 正式启动方式

正式启动链路已经收口，当前只允许：

- 首次初始化：`.\scripts\register_scheduled_task.ps1`
- 日常启动：`.\古墓迷途.cmd`
- 底层触发：`.\scripts\run_via_task.ps1`

不要把 `python main.py`、`py main.py`、或直接调用虚拟环境解释器当成日常启动方式。`main.py` 是代码入口，不是运维入口。

## 当前系统最重要的真相

- canonical SQLite 是唯一真实数据源。
- 昵称是 canonical 账号记录的唯一键。
- 网页层不是主真源，只能查看，或对少数字段做最小修改后回写 canonical 并回读确认。
- `已准备` 是正式状态值，不是展示映射。
- 56 分钟轻量落库、2 小时 50 分抢购活跃态统计，仍是当前主线硬规则。

## 当前已进入主线基线的能力

当前主线不只是“抢购脚本本体”，还包括：

- canonical 账号库与轮次写回
- 启动后预上架，再进入抢购主循环
- 执行位调度、切区、换号、昵称校验
- 悬浮窗正常模式显示增强与 F12 暂停/恢复
- 本机网页查看与单账号 3 字段最小修改
- 本机配置外置与 `C:\py666` live 路径优先
- 临时抢购模式（启动菜单 `[2]`）
- 双机网页汇总与远端镜像的第一阶段能力

## 当前明确未纳入范围

第一次接手时，尤其不要误判下面这些事情已经做完：

- 不做双向同步
- 不共享 SQLite
- 不允许把远端镜像当真源
- 不允许把公网网页当成通用写入口
- `thread_history` 不是当前系统说明书
- 历史线程“阶段完成”不等于整个系统已经封板

## 你读完这份后应该做什么

如果你想先建立全局理解，继续读：

1. [01_system_overview.md](01_system_overview.md)
2. [02_module_map.md](02_module_map.md)
3. [03_runtime_and_data.md](03_runtime_and_data.md)
4. [04_operations_and_acceptance.md](04_operations_and_acceptance.md)

下一份建议阅读： [01_system_overview.md](01_system_overview.md)

- [`docs/knowledge_base/08_canonical_fields_and_api.md`](docs/knowledge_base/08_canonical_fields_and_api.md)：canonical 字段清单、跨模块函数签名、常见误用
- [`docs/knowledge_base/09_ui_conventions.md`](docs/knowledge_base/09_ui_conventions.md)：配色、字体、悬浮窗架构规则
- [`docs/knowledge_base/10_naming_gotchas.md`](docs/knowledge_base/10_naming_gotchas.md)：命名陷阱与历史遗留，新人必读
