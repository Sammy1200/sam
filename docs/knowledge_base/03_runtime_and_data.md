# 运行态与数据语义

这份文档用于统一数据口径。第一次接手时，很多误解都来自“看到了字段，但不知道它是真值、派生值还是快照值”。

## canonical SQLite 的角色

canonical SQLite 是当前系统的唯一真实数据源。

当前最核心的 canonical 表是：

- 表名：`account_stats`
- 主键：`nickname`

它负责承载当前主线认可的账号事实，包括：

- 道具库存基线
- 当前执行位
- 当前轮次成功/失败/上架计数
- 当前余额
- 运行时间相关字段
- 账号状态
- 时间锚点字段

网页、悬浮窗、远端镜像都可以引用它，但不能替代它。

## 为什么昵称是唯一键

当前代码里 `account_stats` 以 `nickname TEXT PRIMARY KEY` 建表。执行位虽然重要，但只是：

- 调度入口
- 启动器选区提示
- 兼容读取和建档补位的辅助信息

它不是 canonical 的唯一键。原因是：

- 执行位会在调度链路中轮换
- 同一执行位可能先出现种子记录，再映射到真实昵称
- 真正被业务和网页共同识别的账号身份仍是昵称

所以“执行位可变，昵称主键不变”是当前系统基本语义。

## `updated_at` 与 `last_account_end_time` 的区别

这两个字段经常被混用，但它们不是一回事。

### `updated_at`

`updated_at` 表示这条 canonical 记录最近一次被写入或刷新时间。常见来源包括：

- 网页最小修改写回
- 轻量落库
- 最终写回
- 暂停 / 恢复快照

它反映“这条记录最近什么时候被系统改过”。

### `last_account_end_time`

`last_account_end_time` 表示当前账号最近一次完成本轮并结束账号流程的时间锚点。它更接近“最后下号 / 本轮结束时间”。

它不会在每次轻量更新时都改，而是在最终写回等结束阶段更重要。

### 不要怎么理解

- 不要把 `updated_at` 当成“最后下号时间”
- 不要把 `last_account_end_time` 当成“最近任何字段改动时间”

## 2 小时 50 分与 24 小时窗口规则

### 2 小时 50 分

当前代码常量 `ACCOUNT_MAX_PURCHASE_SECONDS` 等于 2 小时 50 分。

它的语义是：

- 只统计真正抢购循环活跃态
- 进入抢购循环前会初始化或恢复运行窗口
- 暂停、上架、冷却等待等不应被错误计入活跃抢购时间
- 达到阈值时，会记录账号达到上限的时刻，并进入 `抢购时长已到` 相关收尾

### 24 小时窗口

当前实现使用 `ACCOUNT_LIMIT_COOLDOWN_SECONDS = (24 * 60 + 1) * 60`，也就是 **24 小时 01 分**。

这有两个重要含义：

- 冷却恢复判断以这个窗口计算
- 运行窗口滚动也使用这个常量

注意：

- “24 小时 05 分”只属于历史口径，不是当前规则。
- 当前代码和当前文档统一按 24 小时 01 分理解。

## 运行态字段、持久化字段、派生字段

### 运行态字段

运行态字段主要存在于 `state.py` 中，例如：

- `current_nickname`
- `current_execution_slot`
- `round_purchase_success_count`
- `round_listing_success_count`
- `round_purchase_fail_count`
- `round_current_balance`
- `overlay_status`
- `purchase_timer_active`

它们表示“当前进程此刻记住了什么”，不等于已经落入真源。

### 持久化字段

持久化字段主要落在 canonical `account_stats` 表中，例如：

- `baseline_item_count`
- `current_execution_slot`
- `round_purchase_success_count`
- `round_listing_success_count`
- `round_purchase_fail_count`
- `current_balance`
- `purchase_running_seconds`
- `runtime_window_start_time`
- `round_status`
- `last_limit_time`
- `last_account_end_time`
- `updated_at`

这些字段在写入 SQLite 后，才是系统正式事实。

### 派生字段

派生字段通常由 `account_view_repo.py` 在读取时计算，例如：

- `allow_purchase`
- `allow_start_time`
- `cooldown_remaining_seconds`
- `runtime_window_remaining_seconds`
- `runtime_window_remaining_text`
- `updated_at_relative`
- `inventory_quantity`

这些字段方便展示和诊断，但不是直接存储真值。

## 哪些值是真值，哪些只是快照或展示值

### 真值

下面这些值在 canonical 中是真值：

- `baseline_item_count`
- `current_balance`
- `round_status`
- `purchase_running_seconds`
- `runtime_window_start_time`
- `last_limit_time`
- `last_account_end_time`
- `updated_at`

### 辅助快照

下面这些值是辅助快照，不应替代 canonical：

- `thread6_runtime.sqlite3` 中的当前执行位与当前昵称
- `remote_sync_mirror.sqlite3` 中的远端镜像行
- 网页上的相对时间、剩余时间、健康摘要

### 展示态

下面这些值只用于显示：

- 悬浮窗里的 `新/沿/待确认` 余额前缀
- `updated_at_relative`
- 运行窗口剩余文案
- 冷却剩余文案

## 常用状态值语义

当前主线常用状态值至少包括：

- `运行中`
  当前账号正在正式运行链路中。
- `账号限制`
  账号命中了限制类结束条件，需要进入冷却恢复窗口。
- `余额不足`
  当前有效余额低于阈值，触发本轮结束与调度。
- `抢购时长已到`
  当前账号已达到 2 小时 50 分活跃抢购上限。
- `已准备`
  正式状态值，表示账号已恢复到可重新进入流程的准备态。
- `未知异常`
  当前链路未能按已知出口正常收束。
- `人工暂停`
  F12 暂停后的正式状态。

补充说明：

- `正常结束`、`手动结束` 等旧口径在归一时会被收束到 `人工暂停` 等当前枚举，不应再当成新的正式状态扩散。

## 自动恢复为 `已准备` 的规则

当前自动恢复规则是固定的：

- 当前状态为 `余额不足`、`账号限制` 或 `抢购时长已到`
- 冷却剩余时间 `<= 0`

满足时，系统会把状态自动恢复为 `已准备`。

网页手动改成 `已准备` 时，也要同步满足：

- 可运行时间恢复为 2 小时 50 分
- 冷却剩余时间归零

下一份建议阅读： [04_operations_and_acceptance.md](04_operations_and_acceptance.md)
